#!/usr/bin/env python3
"""Converte frames ainda pendentes em embeddings visuais e grava no pgvector."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Iterable

from db_support import ROOT, apply_migrations, connect, env_int, load_env
from model_downloads import ensure_all_models, vision_embedding_id


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
FRAME_NUMBER = re.compile(r"(\d+)(?=\.[^.]+$)")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def frame_number(path: Path) -> int:
    match = FRAME_NUMBER.search(path.name)
    if not match:
        raise RuntimeError(f"Não foi possível identificar o número do frame: {path}")
    return int(match.group(1))


def numbered_folders(done: Path) -> Iterable[tuple[int, Path]]:
    if not done.is_dir():
        raise RuntimeError(f"Pasta Done não encontrada: {done}")
    folders = [(int(path.name), path) for path in done.iterdir() if path.is_dir() and path.name.isdigit()]
    yield from sorted(folders)


def metadata_for(folder: Path) -> dict[str, object]:
    path = folder / "metadata.json"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Metadata inválida em {path}: {error}") from error


def discover(connection, done: Path, model_name: str) -> int:
    total = 0
    with connection.cursor() as cursor:
        for folder_number, folder in numbered_folders(done):
            metadata = metadata_for(folder)
            images = sorted(
                (path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES),
                key=frame_number,
            )
            cursor.execute(
                """
                INSERT INTO videos (
                    folder_number, folder_path, source_path, fps, width, height,
                    duration_seconds, expected_frames, discovered_frames, embedding_model
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (folder_number) DO UPDATE SET
                    folder_path = EXCLUDED.folder_path,
                    source_path = EXCLUDED.source_path,
                    fps = EXCLUDED.fps,
                    width = EXCLUDED.width,
                    height = EXCLUDED.height,
                    duration_seconds = EXCLUDED.duration_seconds,
                    expected_frames = EXCLUDED.expected_frames,
                    discovered_frames = EXCLUDED.discovered_frames,
                    updated_at = now()
                RETURNING id, status, embedding_model, processed_frames
                """,
                (folder_number, str(folder.resolve()), metadata.get("arquivo_origem"), metadata.get("fps"),
                 metadata.get("largura"), metadata.get("altura"), metadata.get("duracao_segundos"),
                 metadata.get("frames_extraidos") or metadata.get("frames_detectados"), len(images), model_name),
            )
            video_id, status, previous_model, processed_frames = cursor.fetchone()
            if status == "completed" and previous_model == model_name and processed_frames == len(images):
                print(f"Done/{folder.name}: já processada; ignorando.")
                continue
            for image in images:
                number = frame_number(image)
                digest = sha256_file(image)
                try:
                    relative = str(image.resolve().relative_to(ROOT))
                except ValueError:
                    relative = str(image.resolve())
                cursor.execute(
                    """
                    INSERT INTO frames (video_id, frame_number, relative_path, file_sha256)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (video_id, frame_number) DO UPDATE SET
                        relative_path = EXCLUDED.relative_path,
                        file_sha256 = EXCLUDED.file_sha256,
                        embedding = CASE WHEN frames.file_sha256 <> EXCLUDED.file_sha256 THEN NULL ELSE frames.embedding END,
                        status = CASE WHEN frames.file_sha256 <> EXCLUDED.file_sha256 THEN 'pending' ELSE frames.status END,
                        updated_at = now()
                    """,
                    (video_id, number, relative, digest),
                )
                total += 1
    connection.commit()
    return total


def select_device(torch, requested: str) -> str:
    if requested != "auto":
        return requested
    if torch.cuda.is_available():  # PyTorch usa a API cuda também em builds ROCm.
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_encoder(model_path: Path, device_name: str):
    try:
        import torch
        import torchvision  # noqa: F401 - exigido pelo AutoImageProcessor
        from PIL import Image
        from transformers import AutoImageProcessor, AutoModel
    except ImportError as error:
        raise RuntimeError(
            "Dependências de visão ausentes. No Arch/ROCm execute: "
            "sudo pacman -S python-pytorch-rocm python-torchvision. "
            "Depois reinstale requirements.txt no ambiente virtual."
        ) from error
    device = select_device(torch, device_name)
    print(f"Carregando {model_path} em {device}...")
    processor = AutoImageProcessor.from_pretrained(str(model_path), local_files_only=True, use_fast=False)
    # O config oficial referencia a implementação NomicBert mantida pela própria
    # Nomic. Se ainda ausente, esse pequeno módulo também vai para Models/.huggingface.
    model = AutoModel.from_pretrained(
        str(model_path),
        trust_remote_code=True,
        code_revision=os.environ.get("VISION_CODE_REVISION"),
    ).eval().to(device)
    return torch, Image, processor, model, device


def batches(items: list[tuple], size: int) -> Iterable[list[tuple]]:
    for start in range(0, len(items), size):
        yield items[start:start + size]


def encode_batch(torch, Image, processor, model, device: str, paths: list[Path]):
    images = []
    try:
        for path in paths:
            images.append(Image.open(path).convert("RGB"))
        inputs = processor(images=images, return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with torch.inference_mode():
            output = model(**inputs).last_hidden_state
            if output.ndim != 3:
                raise RuntimeError(f"Saída visual inesperada: {tuple(output.shape)}")
            # Receita oficial do Nomic Vision: token CLS, depois norma L2.
            output = output[:, 0]
            output = torch.nn.functional.normalize(output, p=2, dim=1)
        return output.detach().float().cpu().tolist()
    finally:
        for image in images:
            image.close()


def pending_frames(connection, model_name: str, limit: int | None) -> list[tuple]:
    query = """
        SELECT f.id, f.video_id, f.relative_path
        FROM frames f
        WHERE f.embedding IS NULL OR f.embedding_model IS DISTINCT FROM %s
        ORDER BY f.video_id, f.frame_number
    """
    params: list[object] = [model_name]
    if limit is not None:
        query += " LIMIT %s"
        params.append(limit)
    with connection.cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def update_video_states(connection, model_name: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE videos v SET
                processed_frames = summary.done,
                status = CASE WHEN summary.done = summary.total AND summary.total > 0 THEN 'completed' ELSE 'pending' END,
                embedding_model = %s,
                completed_at = CASE WHEN summary.done = summary.total AND summary.total > 0 THEN now() ELSE NULL END,
                updated_at = now()
            FROM (
                SELECT video_id, count(*) AS total,
                       count(*) FILTER (WHERE embedding IS NOT NULL AND embedding_model = %s) AS done
                FROM frames GROUP BY video_id
            ) summary
            WHERE v.id = summary.video_id
            """,
            (model_name, model_name),
        )
    connection.commit()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--done", type=Path, default=ROOT / "Done")
    parser.add_argument("--limit", type=int, help="processa no máximo N frames (útil para teste)")
    parser.add_argument("--scan-only", action="store_true", help="registra vídeos/frames no banco sem gerar vetores")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_env()
    _, vision_repo, model_path = ensure_all_models()
    model_name = vision_embedding_id(vision_repo)
    batch_size = env_int("FRAME_BATCH_SIZE", 16)
    expected_dim = env_int("EMBEDDING_DIM", 768)
    if expected_dim != 768:
        raise RuntimeError("A migration atual usa vector(768); EMBEDDING_DIM precisa ser 768.")

    with connect() as connection:
        apply_migrations(connection)
        discovered = discover(connection, args.done.expanduser().resolve(), model_name)
        print(f"Frames catalogados: {discovered}")
        if args.scan_only:
            return 0
        pending = pending_frames(connection, model_name, args.limit)
        if not pending:
            print("Nenhum frame pendente.")
            update_video_states(connection, model_name)
            return 0

        torch, Image, processor, model, device = load_encoder(
            model_path, os.environ.get("VISION_DEVICE", "auto")
        )
        processed = 0
        for group in batches(pending, batch_size):
            paths = [Path(row[2]) if Path(row[2]).is_absolute() else ROOT / row[2] for row in group]
            vectors = encode_batch(torch, Image, processor, model, device, paths)
            if any(len(vector) != expected_dim for vector in vectors):
                raise RuntimeError(f"O encoder não retornou vetores de {expected_dim} dimensões.")
            with connection.cursor() as cursor:
                for (frame_id, video_id, _), vector in zip(group, vectors, strict=True):
                    vector_literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
                    cursor.execute(
                        """
                        UPDATE frames SET embedding = %s::vector, embedding_model = %s,
                            status = 'completed', last_error = NULL, processed_at = now(), updated_at = now()
                        WHERE id = %s
                        """,
                        (vector_literal, model_name, frame_id),
                    )
            connection.commit()
            processed += len(group)
            print(f"Processados: {processed}/{len(pending)}")
        update_video_states(connection, model_name)
    print("Vetorização concluída.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(1)

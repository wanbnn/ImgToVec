#!/usr/bin/env python3
"""Extrai todos os frames de um vídeo para a próxima pasta numerada em Done/."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"'{name}' não foi encontrado. Instale o FFmpeg e tente novamente.")
    return path


def inspect_video(video: Path) -> dict[str, object]:
    ffprobe = require_tool("ffprobe")
    command = [ffprobe, "-v", "error", "-select_streams", "v:0", "-count_frames",
               "-show_entries", "stream=avg_frame_rate,r_frame_rate,nb_frames,nb_read_frames,width,height,duration",
               "-of", "json", str(video)]
    result = subprocess.run(command, text=True, capture_output=True, check=True)
    streams = json.loads(result.stdout).get("streams", [])
    if not streams:
        raise RuntimeError("O arquivo não contém uma faixa de vídeo.")
    stream = streams[0]
    raw_rate = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    try:
        fps = float(Fraction(str(raw_rate)))
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    frames = stream.get("nb_read_frames") or stream.get("nb_frames")
    return {
        "fps": fps,
        "fps_original": raw_rate,
        "frames_detectados": int(frames) if str(frames).isdigit() else None,
        "largura": int(stream["width"]),
        "altura": int(stream["height"]),
        "duracao_segundos": float(stream["duration"]) if stream.get("duration") not in (None, "N/A") else None,
    }


def next_numbered_directory(done: Path) -> Path:
    done.mkdir(parents=True, exist_ok=True)
    numbers = [int(item.name) for item in done.iterdir() if item.is_dir() and item.name.isdigit()]
    destination = done / f"{max(numbers, default=0) + 1:04d}"
    destination.mkdir()
    return destination


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="arquivo de vídeo de entrada")
    parser.add_argument("--format", choices=("png", "jpg", "webp"), default="png")
    parser.add_argument("--quality", type=int, default=2, help="qualidade JPG (2 melhor, 31 pior)")
    parser.add_argument("--done", type=Path, default=ROOT / "Done", help="pasta raiz de saída")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    video = args.video.expanduser().resolve()
    if not video.is_file():
        raise RuntimeError(f"Vídeo não encontrado: {video}")
    if not 2 <= args.quality <= 31:
        raise ValueError("--quality deve ficar entre 2 e 31")

    info = inspect_video(video)
    print(f"Vídeo: {info['largura']}x{info['altura']} | {info['fps']:.3f} FPS | "
          f"frames detectados: {info['frames_detectados'] or 'desconhecido'}")
    destination = next_numbered_directory(args.done.expanduser().resolve())
    ffmpeg = require_tool("ffmpeg")
    output = destination / f"frame_%08d.{args.format}"
    command = [ffmpeg, "-hide_banner", "-i", str(video), "-map", "0:v:0", "-fps_mode", "passthrough"]
    if args.format == "jpg":
        command += ["-q:v", str(args.quality)]
    command += [str(output)]
    try:
        subprocess.run(command, check=True)
    except Exception:
        # Remove apenas a pasta recém-criada e vazia/parcial desta execução.
        shutil.rmtree(destination, ignore_errors=True)
        raise

    extracted = sum(1 for item in destination.iterdir() if item.name.startswith("frame_"))
    metadata = {"arquivo_origem": str(video), **info, "frames_extraidos": extracted, "formato": args.format}
    (destination / "metadata.json").write_text(json.dumps(metadata, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Extração concluída: {extracted} frames em {destination}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(1)

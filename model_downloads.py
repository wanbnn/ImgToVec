#!/usr/bin/env python3
"""Download idempotente dos encoders usados pelo pipeline."""

from __future__ import annotations

import os
import json
from pathlib import Path

from db_support import ROOT, load_env


MODELS_DIR = ROOT / "Models"
DEFAULT_TEXT_REPO = "nomic-ai/nomic-embed-text-v1.5-GGUF"
DEFAULT_TEXT_FILE = "nomic-embed-text-v1.5.Q4_K_M.gguf"
DEFAULT_VISION_REPO = "nomic-ai/nomic-embed-vision-v1.5"
DEFAULT_TRANSLATION_REPO = "Helsinki-NLP/opus-mt-ROMANCE-en"
VISION_EMBED_PIPELINE_VERSION = "cls-l2-v2"


def vision_embedding_id(repo: str) -> str:
    """Identificador persistido; muda quando o pré-processamento muda."""
    return f"{repo}@{VISION_EMBED_PIPELINE_VERSION}"


def normalize_vision_config(destination: Path) -> None:
    """Corrige tipos numéricos legados rejeitados pelo Transformers 5+."""
    config_path = destination / "config.json"
    if not config_path.is_file():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    changed = False
    for field in ("n_inner",):
        value = config.get(field)
        if isinstance(value, float) and value.is_integer():
            config[field] = int(value)
            changed = True
    if changed:
        config_path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"Configuração do encoder visual normalizada: {config_path}")


def huggingface_api():
    try:
        from huggingface_hub import hf_hub_download, snapshot_download
    except ImportError as error:
        raise RuntimeError("Dependência ausente. Execute: python3 -m pip install -r requirements.txt") from error
    return hf_hub_download, snapshot_download


def resolve_project_path(value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else ROOT / path


def ensure_text_model() -> Path:
    configured = os.environ.get("LLAMA_EMBED_MODEL", f"Models/{DEFAULT_TEXT_FILE}")
    destination = resolve_project_path(configured)
    if destination.is_file():
        print(f"Modelo textual disponível: {destination}")
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    repo = os.environ.get("LLAMA_EMBED_REPO", DEFAULT_TEXT_REPO)
    filename = os.environ.get("LLAMA_EMBED_FILE", destination.name)
    hf_hub_download, _ = huggingface_api()
    print(f"Baixando {repo}/{filename} para {destination.parent}...")
    downloaded = Path(hf_hub_download(repo_id=repo, filename=filename, local_dir=destination.parent))
    if downloaded.resolve() != destination.resolve():
        downloaded.replace(destination)
    return destination


def ensure_vision_model() -> tuple[str, Path]:
    repo = os.environ.get("VISION_EMBED_MODEL", DEFAULT_VISION_REPO)
    configured_dir = os.environ.get("VISION_EMBED_DIR", "Models/nomic-embed-vision-v1.5")
    destination = resolve_project_path(configured_dir)
    required = (destination / "config.json", destination / "preprocessor_config.json", destination / "model.safetensors")
    if all(path.is_file() for path in required):
        normalize_vision_config(destination)
        print(f"Modelo visual disponível: {destination}")
        return repo, destination
    destination.mkdir(parents=True, exist_ok=True)
    _, snapshot_download = huggingface_api()
    print(f"Baixando {repo} para {destination}...")
    snapshot_download(
        repo_id=repo,
        local_dir=destination,
        allow_patterns=["*.json", "*.safetensors", "*.py"],
    )
    missing = [str(path.name) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Download visual incompleto; arquivos ausentes: {', '.join(missing)}")
    normalize_vision_config(destination)
    return repo, destination


def ensure_translation_model() -> tuple[str, Path]:
    repo = os.environ.get("TRANSLATION_MODEL", DEFAULT_TRANSLATION_REPO)
    configured_dir = os.environ.get("TRANSLATION_MODEL_DIR", "Models/opus-mt-ROMANCE-en")
    destination = resolve_project_path(configured_dir)
    required = (destination / "config.json", destination / "tokenizer_config.json")
    weights_present = any(destination.glob("*.safetensors")) or any(destination.glob("pytorch_model*.bin"))
    if all(path.is_file() for path in required) and weights_present:
        print(f"Tradutor disponível: {destination}")
        return repo, destination
    destination.mkdir(parents=True, exist_ok=True)
    _, snapshot_download = huggingface_api()
    print(f"Baixando tradutor {repo} para {destination}...")
    snapshot_download(
        repo_id=repo,
        local_dir=destination,
        allow_patterns=["*.json", "*.safetensors", "pytorch_model*.bin", "*.model", "*.spm", "*.txt"],
    )
    if not all(path.is_file() for path in required):
        raise RuntimeError(f"Download do tradutor incompleto em {destination}")
    return repo, destination


def ensure_all_models() -> tuple[Path, str, Path]:
    load_env()
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    # Pesos, metadados e módulos remotos confiáveis permanecem dentro do projeto.
    os.environ.setdefault("HF_HOME", str(MODELS_DIR / ".huggingface"))
    os.environ.setdefault("HF_MODULES_CACHE", str(MODELS_DIR / ".huggingface" / "modules"))
    text_path = ensure_text_model()
    vision_id, vision_path = ensure_vision_model()
    return text_path, vision_id, vision_path

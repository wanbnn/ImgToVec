"""Encoder visual e consulta pgvector compartilhados pelo servidor HTTP."""

from __future__ import annotations

import io
import atexit
import json
import math
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db_support import connect, load_env  # noqa: E402
from model_downloads import ensure_all_models  # noqa: E402
from process_frame_vectors import load_encoder  # noqa: E402


def vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(f"{value:.9g}" for value in vector) + "]"


def search_database(vector: list[float], model_name: str, limit: int) -> list[dict]:
    literal = vector_literal(vector)
    with connect() as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT f.id, v.folder_number, f.frame_number, f.relative_path,
                   1 - (f.embedding <=> %s::vector) AS similarity,
                   v.source_path, v.fps
            FROM frames f
            JOIN videos v ON v.id = f.video_id
            WHERE f.embedding IS NOT NULL AND f.embedding_model = %s
            ORDER BY f.embedding <=> %s::vector
            LIMIT %s
            """,
            (literal, model_name, literal, limit),
        )
        return [
            {"id": row[0], "folder": row[1], "frame": row[2], "path": row[3],
             "similarity": float(row[4]), "source": row[5], "fps": row[6]}
            for row in cursor.fetchall()
        ]


class VisualSearch:
    def __init__(self):
        load_env()
        self._lock = threading.Lock()
        self._encoder = None
        self.model_name = None

    def _load(self):
        if self._encoder is None:
            _, self.model_name, model_path = ensure_all_models()
            self._encoder = load_encoder(model_path, "auto")
        return self._encoder

    def encode(self, image_bytes: bytes) -> list[float]:
        torch, Image, processor, model, device = self._load()
        with Image.open(io.BytesIO(image_bytes)) as source:
            image = source.convert("RGB")
        inputs = processor(images=[image], return_tensors="pt")
        inputs = {key: value.to(device) for key, value in inputs.items()}
        with self._lock, torch.inference_mode():
            output = model(**inputs).last_hidden_state
            if output.ndim == 3:
                output = output.mean(dim=1)
            output = torch.nn.functional.normalize(output, p=2, dim=1)
        vector = output[0].detach().float().cpu().tolist()
        if len(vector) != 768:
            raise RuntimeError(f"Encoder retornou {len(vector)} dimensões; esperado: 768")
        return vector

    def search(self, image_bytes: bytes, limit: int) -> list[dict]:
        vector = self.encode(image_bytes)
        return search_database(vector, self.model_name, limit)

    def frame_path(self, frame_id: int) -> Path | None:
        with connect() as connection, connection.cursor() as cursor:
            cursor.execute("SELECT relative_path FROM frames WHERE id = %s AND embedding IS NOT NULL", (frame_id,))
            row = cursor.fetchone()
        if not row:
            return None
        candidate = Path(row[0]) if Path(row[0]).is_absolute() else PROJECT_ROOT / row[0]
        candidate = candidate.resolve()
        done = (PROJECT_ROOT / "Done").resolve()
        if not candidate.is_file() or not candidate.is_relative_to(done):
            return None
        return candidate


visual_search = VisualSearch()


class TextSearch:
    def __init__(self):
        self._lock = threading.Lock()
        self._process = None
        self._model_path = None
        self._vision_model_name = None
        self.port = int(os.environ.get("LLAMA_EMBED_PORT", "8081"))
        atexit.register(self.close)

    def _binary(self) -> Path:
        configured = os.environ.get("LLAMA_SERVER_BIN")
        if configured:
            path = Path(configured).expanduser()
            path = path if path.is_absolute() else PROJECT_ROOT / path
            if path.is_file():
                return path
            raise RuntimeError(f"LLAMA_SERVER_BIN não encontrado: {path}")
        candidates = sorted((PROJECT_ROOT / "llama.cpp").glob("build-*/bin/llama-server"))
        if not candidates:
            raise RuntimeError("llama-server não encontrado. Execute ./build_llama_cpp.py na raiz.")
        preferred = ("build-rocm", "build-cuda", "build-metal", "build-cpu")
        return min(candidates, key=lambda path: preferred.index(path.parents[1].name) if path.parents[1].name in preferred else 99)

    def _request(self, path: str, payload: dict | None = None, timeout: float = 2.0):
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}", data=data,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())

    def _healthy(self) -> bool:
        try:
            self._request("/health", timeout=.5)
            return True
        except Exception:
            return False

    def _start(self):
        text_model, self._vision_model_name, _ = ensure_all_models()
        self._model_path = text_model
        if self._healthy():
            return
        command = [
            str(self._binary()), "--model", str(text_model), "--embedding",
            "--pooling", "mean", "--embd-normalize", "2", "--n-gpu-layers", "all",
            "--host", "127.0.0.1", "--port", str(self.port), "--no-webui",
        ]
        log_path = PROJECT_ROOT / "research" / ".llama-server.log"
        self._log = log_path.open("ab")
        self._process = subprocess.Popen(command, stdout=self._log, stderr=subprocess.STDOUT)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if self._process.poll() is not None:
                raise RuntimeError(f"llama-server encerrou durante a inicialização. Consulte {log_path}")
            if self._healthy():
                return
            time.sleep(.25)
        raise RuntimeError("llama-server não ficou pronto em 30 segundos")

    def encode(self, query: str) -> list[float]:
        query = " ".join(query.split()).strip()
        if not query:
            raise ValueError("Digite uma descrição para pesquisar")
        if len(query) > 1000:
            raise ValueError("A consulta deve ter no máximo 1000 caracteres")
        with self._lock:
            self._start()
            response = self._request(
                "/v1/embeddings",
                {"model": "nomic-embed-text-v1.5", "input": f"search_query: {query}", "encoding_format": "float"},
                timeout=30,
            )
        vector = response["data"][0]["embedding"]
        if len(vector) != 768:
            raise RuntimeError(f"Nomic Text retornou {len(vector)} dimensões; esperado: 768")
        # Nomic v1.5 aplica LayerNorm ao embedding textual antes da normalização
        # L2 para alinhá-lo ao espaço do encoder visual.
        mean = sum(vector) / len(vector)
        variance = sum((value - mean) ** 2 for value in vector) / len(vector)
        layer_norm = [(value - mean) / math.sqrt(variance + 1e-5) for value in vector]
        norm = math.sqrt(sum(value * value for value in layer_norm))
        return [value / norm for value in layer_norm]

    def search(self, query: str, limit: int) -> list[dict]:
        vector = self.encode(query)
        return search_database(vector, self._vision_model_name, limit)

    def close(self):
        if self._process and self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
        if hasattr(self, "_log"):
            self._log.close()


text_search = TextSearch()

"""Encoder visual e consulta pgvector compartilhados pelo servidor HTTP."""

from __future__ import annotations

import io
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from db_support import connect  # noqa: E402
from model_downloads import ensure_all_models  # noqa: E402
from process_frame_vectors import load_encoder  # noqa: E402


class VisualSearch:
    def __init__(self):
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
        literal = "[" + ",".join(f"{value:.9g}" for value in vector) + "]"
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
                (literal, self.model_name, literal, limit),
            )
            return [
                {"id": row[0], "folder": row[1], "frame": row[2], "path": row[3],
                 "similarity": float(row[4]), "source": row[5], "fps": row[6]}
                for row in cursor.fetchall()
            ]

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

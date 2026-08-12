from pathlib import Path

from src.server import MAX_UPLOAD, PUBLIC
from model_downloads import vision_embedding_id


def test_server_limits_uploads():
    assert MAX_UPLOAD == 15 * 1024 * 1024


def test_public_assets_exist():
    assert PUBLIC == Path(__file__).resolve().parents[1] / "public"
    assert (PUBLIC / "app.js").is_file()
    assert (PUBLIC / "styles.css").is_file()
    assert (PUBLIC / "search-modes.css").is_file()


def test_embedding_version_records_cls_pipeline():
    assert vision_embedding_id("nomic-vision").endswith("@cls-l2-v2")

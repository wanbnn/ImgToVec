from pathlib import Path

from src.server import MAX_UPLOAD, PUBLIC


def test_server_limits_uploads():
    assert MAX_UPLOAD == 15 * 1024 * 1024


def test_public_assets_exist():
    assert PUBLIC == Path(__file__).resolve().parents[1] / "public"
    assert (PUBLIC / "app.js").is_file()
    assert (PUBLIC / "styles.css").is_file()
    assert (PUBLIC / "search-modes.css").is_file()

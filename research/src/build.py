"""Gera os assets SSR estáticos; a API continua sendo servida por src.server."""

import shutil
from pathlib import Path

from src.app import render_document


def build(output=Path("dist")):
    output = Path(output)
    if output.exists():
        shutil.rmtree(output)
    shutil.copytree("public", output)
    (output / "index.html").write_text(render_document(), encoding="utf-8")
    return output.resolve()


if __name__ == "__main__":
    print(f"[OK] Build em {build()}")

#!/usr/bin/env python3
"""Baixa para Models/ todos os encoders ausentes."""

import sys

from model_downloads import ensure_all_models


if __name__ == "__main__":
    try:
        text, vision_id, vision = ensure_all_models()
        print(f"Modelo textual: {text}")
        print(f"Modelo visual ({vision_id}): {vision}")
    except Exception as error:
        print(f"Erro: {error}", file=sys.stderr)
        raise SystemExit(1)

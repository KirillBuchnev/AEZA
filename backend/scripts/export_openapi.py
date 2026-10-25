"""Пишет backend/openapi.json из запущенного приложения.

Файл генерируется, вручную не редактируется. Запускать после изменения эндпоинта:
    python backend/scripts/export_openapi.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "openapi.json"


def generated_spec() -> dict:
    os.environ.setdefault("AEZA_DATABASE_PATH", str(BACKEND / "data-openapi-check.db"))
    sys.path.insert(0, str(BACKEND))
    from app.main import app

    return app.openapi()


def main() -> None:
    OUT.write_text(json.dumps(generated_spec(), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

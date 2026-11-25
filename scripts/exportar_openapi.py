"""Genera el contrato: `python -m scripts.exportar_openapi` escribe docs/api/openapi.json."""

import json
import os
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"


def generar() -> str:
    # create_app() lee la configuración, pero generar el contrato no usa la base de datos.
    os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://contrato@localhost/contrato")
    from app.main import create_app

    return json.dumps(create_app().openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def main() -> int:
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(generar(), encoding="utf-8")
    print(f"Contrato escrito en {RUTA.relative_to(RUTA.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

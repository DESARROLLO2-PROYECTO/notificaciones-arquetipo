"""Genera el contrato: `python -m scripts.exportar_openapi` escribe docs/api/openapi.json."""

import json
from pathlib import Path

RUTA = Path(__file__).resolve().parent.parent / "docs" / "api" / "openapi.json"


def generar() -> str:
    from app.api.aplicacion import construir_app

    return (
        json.dumps(construir_app().openapi(), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    )


def main() -> int:
    RUTA.parent.mkdir(parents=True, exist_ok=True)
    RUTA.write_text(generar(), encoding="utf-8")
    print(f"Contrato escrito en {RUTA.relative_to(RUTA.parent.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

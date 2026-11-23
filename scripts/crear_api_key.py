"""Crea una API Key con `python -m scripts.crear_api_key --rol inventario`."""

from scripts.api_keys import main

if __name__ == "__main__":
    raise SystemExit(main(comando="generar"))

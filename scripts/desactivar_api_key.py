"""Desactiva una API Key con `python -m scripts.desactivar_api_key --id 1`."""

from scripts.api_keys import main

if __name__ == "__main__":
    raise SystemExit(main(comando="desactivar"))

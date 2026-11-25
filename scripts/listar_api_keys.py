"""Lista las API Keys (sin su valor) con `python -m scripts.listar_api_keys`."""

from scripts.api_keys import main

if __name__ == "__main__":
    raise SystemExit(main(["listar"]))

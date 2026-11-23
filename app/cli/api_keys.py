"""Conserva el comando `python -m app.cli.api_keys` para el uso anterior."""

from scripts.api_keys import main

if __name__ == "__main__":
    raise SystemExit(main())

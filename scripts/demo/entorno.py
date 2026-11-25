"""Acceso al entorno local de Docker: comandos de consola, SQL de evidencia y registros.

La demo por criterios necesita mirar dentro del servicio (la base de datos, los registros y las
herramientas de consola de HU-NOT-11). Con `docker compose` local se hace con `docker compose exec`.
"""

import subprocess
import time
from pathlib import Path
from typing import Protocol


class Entorno(Protocol):
    """Lo que la demo pide al entorno; en las pruebas lo reemplaza una versión en proceso."""

    disponible: bool

    def cli(self, *args: str) -> tuple[int, str, str]:
        """Ejecuta `python -m <args>` dentro del servicio. Devuelve (código, salida, errores)."""
        ...

    def texto_cli(self, *args: str) -> str:
        """El comando tal como se escribe en la terminal, para mostrarlo."""
        ...

    def sql(self, consulta: str) -> list[list[str]]: ...

    def registros(self) -> str: ...

    def parar_bd(self) -> bool: ...

    def iniciar_bd(self) -> bool: ...


class DockerLocal:
    def __init__(self, raiz: Path, servicio: str = "api", base: str = "db") -> None:
        self._raiz = raiz
        self._servicio = servicio
        self._base = base
        self.disponible = self._corre(servicio)

    def _compose(
        self, *args: str, entrada: str | None = None, espera_s: float = 60
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # noqa: S603 - comando fijo, sin entrada del usuario
            ["docker", "compose", *args],
            cwd=self._raiz, input=entrada, capture_output=True, text=True,
            check=False, timeout=espera_s,
        )  # fmt: skip

    def _corre(self, servicio: str) -> bool:
        try:
            r = self._compose("ps", "-q", servicio, espera_s=15)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return r.returncode == 0 and bool(r.stdout.strip())

    def cli(self, *args: str) -> tuple[int, str, str]:
        r = self._compose("exec", "-T", self._servicio, "python", "-m", *args)
        return r.returncode, r.stdout, r.stderr

    def texto_cli(self, *args: str) -> str:
        return f"docker compose exec -T {self._servicio} python -m {' '.join(args)}"

    def sql(self, consulta: str) -> list[list[str]]:
        r = self._compose(
            "exec", "-T", self._base, "sh", "-c",
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F"|" -v ON_ERROR_STOP=1',
            entrada=consulta,
        )  # fmt: skip
        if r.returncode != 0:
            raise RuntimeError(f"La consulta falló: {r.stderr.strip()[:200]}")
        return [linea.split("|") for linea in r.stdout.splitlines() if linea]

    def registros(self) -> str:
        r = self._compose("logs", "--no-color", "--tail", "2000", self._servicio)
        return r.stdout + r.stderr

    def parar_bd(self) -> bool:
        return self._compose("stop", self._base).returncode == 0

    def iniciar_bd(self) -> bool:
        if self._compose("start", self._base).returncode != 0:
            return False
        for _ in range(30):  # espera a que acepte consultas
            try:
                self.sql("select 1")
                return True
            except (RuntimeError, subprocess.TimeoutExpired):
                time.sleep(2)
        return False

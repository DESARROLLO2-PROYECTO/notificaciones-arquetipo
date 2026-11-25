"""Salida del demo: texto legible para una persona, con colores y pausas opcionales."""

import json
import textwrap
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_COLORES = {
    "titulo": "1;36",
    "escena": "1;35",
    "ok": "32",
    "mal": "1;31",
    "tenue": "2",
    "equipo": "1;33",
    "negrita": "1",
}


@dataclass(frozen=True)
class Respuesta:
    estado: int
    cuerpo: Any
    ms: float


@dataclass(frozen=True)
class Resultado:
    escena: str
    descripcion: str
    correcto: bool


_FRASES_HTTP = {
    200: "OK",
    201: "Created",
    401: "Unauthorized",
    403: "Forbidden",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
}


class Salida:
    def __init__(
        self,
        color: bool,
        pausar: bool,
        escribir: Callable[[str], None] = print,
        leer: Callable[[str], str] = input,
    ) -> None:
        self._color = color
        self._pausar = pausar
        self._escribir = escribir
        self._leer = leer
        self.resultados: list[Resultado] = []

    def _c(self, texto: str, estilo: str) -> str:
        return f"\033[{_COLORES[estilo]}m{texto}\033[0m" if self._color else texto

    def linea(self, texto: str = "") -> None:
        self._escribir(texto)

    def titulo(self, texto: str) -> None:
        barra = "═" * 68
        self.linea(self._c(barra, "titulo"))
        self.linea(self._c(f"  {texto}", "titulo"))
        self.linea(self._c(barra, "titulo"))

    def escena(self, numero: int, titulo: str, explicacion: str) -> None:
        self.linea()
        self.linea(self._c(f"━━ Escena {numero}: {titulo}", "escena"))
        self.linea(self._c(f"   {explicacion}", "tenue"))

    def criterio(self, numero: int, texto: str) -> None:
        """Encabeza un criterio de aceptación con su texto del backlog."""
        self.linea()
        self.linea(self._c(f"━━ Criterio {numero}", "escena"))
        for linea in textwrap.wrap(texto, width=88):
            self.linea(self._c(f"   {linea}", "negrita"))

    def comando(self, texto: str, titulo: str = "Comando de ejemplo") -> None:
        """Un comando que se puede copiar y pegar en la terminal."""
        self.linea(self._c(f"   ▸ {titulo}:", "tenue"))
        for linea in texto.splitlines():
            self.linea(self._c(f"       {linea}", "tenue"))

    def evidencia(self, titulo: str, lineas: list[str]) -> None:
        """Lo que se ve en la base de datos o en los registros, como prueba de lo ocurrido."""
        self.linea(f"   🔎 {titulo}")
        for linea in lineas:
            self.linea(self._c(f"       {linea}", "tenue"))

    def comprobar(self, escena: str, descripcion: str, correcto: bool) -> None:
        """Marca una comprobación (✓ o ✗) y la suma al resumen."""
        marca = self._c("✓", "ok") if correcto else self._c("✗", "mal")
        self.linea(f"   {marca} {descripcion}")
        self.registrar(escena, descripcion, correcto)

    def nota(self, texto: str) -> None:
        self.linea(self._c(f"   ℹ {texto}", "tenue"))

    def solicitud(self, quien: str, metodo: str, ruta: str, cuerpo: dict[str, Any] | None) -> None:
        self.linea()
        self.linea(f"   {self._c(quien, 'equipo')} ▶ {self._c(f'{metodo} {ruta}', 'negrita')}")
        if cuerpo is not None:
            self._bloque(cuerpo)

    def _bloque(self, valor: Any) -> None:
        for linea in _legible(valor):
            self.linea(self._c(f"     {linea}", "tenue"))

    def respuesta(self, r: Respuesta, esperado: int, que_significa: str) -> bool:
        correcto = r.estado == esperado
        frase = _FRASES_HTTP.get(r.estado, "")
        marca = self._c("✓", "ok") if correcto else self._c(f"✗ (se esperaba {esperado})", "mal")
        self.linea(f"   ◀ {self._c(f'{r.estado} {frase}', 'ok' if correcto else 'mal')}"
                   f"  {self._c(f'({r.ms:.0f} ms)', 'tenue')} {marca}")  # fmt: skip
        if r.cuerpo is not None:
            self._bloque(r.cuerpo)
        self.linea(f"   → {que_significa}")
        return correcto

    def registrar(self, escena: str, descripcion: str, correcto: bool) -> None:
        self.resultados.append(Resultado(escena, descripcion, correcto))

    def pausa(self, mensaje: str = "Enter para continuar") -> None:
        if self._pausar:
            self.linea()
            self._leer(self._c(f"   ⏎ {mensaje}... ", "tenue"))

    def pedir_accion(self, mensaje: str) -> None:
        """Una acción manual del presentador: se pide aunque no haya pausas."""
        self.linea()
        self._leer(self._c(f"   ✋ {mensaje} y pulse Enter... ", "equipo"))

    def resumen(self) -> bool:
        self.linea()
        self.titulo("Resumen")
        for r in self.resultados:
            marca = self._c("✓", "ok") if r.correcto else self._c("✗", "mal")
            self.linea(f"  {marca} {r.escena}: {r.descripcion}")
        fallos = [r for r in self.resultados if not r.correcto]
        total = len(self.resultados)
        if fallos:
            self.linea(self._c(f"\n  {len(fallos)} de {total} comprobaciones fallaron", "mal"))
        else:
            self.linea(self._c(f"\n  Todo salió como se esperaba ({total} comprobaciones)", "ok"))
        return not fallos


def _valor(v: Any) -> str:
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False)


def _legible(valor: Any, ancho: int = 84) -> list[str]:
    """Un cuerpo JSON como `clave: valor · clave: valor`: pocas líneas, sin llaves ni comillas."""
    if not isinstance(valor, dict):
        return [_valor(valor)]
    pares = [f"{k}: {_valor(v)}" for k, v in valor.items() if k != "errores"]
    lineas = (
        textwrap.wrap(
            "  ·  ".join(pares), width=ancho, break_long_words=False, break_on_hyphens=False
        )
        if pares
        else []
    )
    for error in valor.get("errores", []) if isinstance(valor.get("errores"), list) else []:
        lineas.append(f"• {error.get('campo')}: {error.get('error')}")
    return lineas

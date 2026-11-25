"""Los equipos falsos: reportan eventos con su propia llave, como lo haría su API real."""

import time
from typing import Any

import httpx

from scripts.demo.salida import Respuesta, Salida


class ClienteApi:
    """Hace las peticiones HTTP y mide cuánto tarda cada una."""

    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    def enviar(
        self, metodo: str, ruta: str, llave: str | None, cuerpo: dict[str, Any] | None = None
    ) -> Respuesta:
        cabeceras = {"X-API-Key": llave} if llave else {}
        inicio = time.monotonic()
        r = self._http.request(metodo, ruta, json=cuerpo, headers=cabeceras)
        ms = (time.monotonic() - inicio) * 1000
        try:
            contenido: Any = r.json()
        except ValueError:
            contenido = r.text or None
        return Respuesta(r.status_code, contenido, ms)


class EquipoFalso:
    def __init__(self, nombre: str, llave: str, api: ClienteApi, salida: Salida) -> None:
        self.nombre = nombre
        self.llave = llave
        self._api = api
        self._salida = salida

    def pedir(
        self, metodo: str, ruta: str, cuerpo: dict[str, Any] | None = None, llave: str | None = None
    ) -> Respuesta:
        """Muestra la petición, la envía con la llave del equipo y devuelve la respuesta."""
        self._salida.solicitud(self.nombre, metodo, ruta, cuerpo)
        return self._api.enviar(metodo, ruta, self.llave if llave is None else llave, cuerpo)


class Inventario(EquipoFalso):
    def __init__(self, llave: str, api: ClienteApi, salida: Salida) -> None:
        super().__init__("Inventario", llave, api, salida)

    @staticmethod
    def stock_bajo(
        producto_id: str,
        nombre: str,
        actual: int,
        minimo: int,
        evento: str = "DETECTADA",
        tipo: str = "STOCK_BAJO_INSUMO",
    ) -> dict[str, Any]:
        return {
            "tipo": tipo,
            "evento": evento,
            "productoId": producto_id,
            "nombre": nombre,
            "stockActual": actual,
            "stockMinimo": minimo,
        }

    def reportar(self, cuerpo: dict[str, Any], llave: str | None = None) -> Respuesta:
        return self.pedir("POST", "/notificaciones", cuerpo, llave)


class Fabricacion(EquipoFalso):
    def __init__(self, llave: str, api: ClienteApi, salida: Salida) -> None:
        super().__init__("Fabricación", llave, api, salida)

    @staticmethod
    def condicion_urgente(
        codigo: str, descripcion: str, evento: str = "DETECTADA"
    ) -> dict[str, Any]:
        return {
            "tipo": "CONDICION_URGENTE",
            "evento": evento,
            "codigoCondicion": codigo,
            "descripcion": descripcion,
        }

    def reportar(self, cuerpo: dict[str, Any]) -> Respuesta:
        return self.pedir("POST", "/notificaciones", cuerpo)


class Administracion(EquipoFalso):
    def __init__(self, llave: str, api: ClienteApi, salida: Salida) -> None:
        super().__init__("Administración", llave, api, salida)

    def ejecutar_ciclo(self, llave: str | None = None) -> Respuesta:
        return self.pedir("POST", "/notificaciones/ciclo", None, llave)

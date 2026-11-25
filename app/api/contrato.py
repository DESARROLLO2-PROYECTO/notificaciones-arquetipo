"""Contrato público (OpenAPI): metadatos, respuestas de error comunes y nombres de operación.

Todo endpoint nuevo debe declarar sus errores con `respuestas(...)` para que la documentación
sea uniforme, y tener `summary` y `description`. `tests/unit/test_openapi.py` lo comprueba.
"""

from typing import Any

from fastapi.routing import APIRoute

from app.api.schemas import ErrorResponse, ErrorValidacionResponse

API_VERSION = "0.3.0"  # versión del contrato (semver); ver docs/api/README.md

DESCRIPCION = """
Módulo de **Notificaciones** del software de fabricación de Cutit Saws. Inventario y Fabricación
le reportan eventos (por ejemplo, stock bajo) y el módulo los registra, evita duplicados, los
publica en una cola interna y los entrega al equipo destino.

## Autenticación

Toda solicitud (excepto `/health` y esta documentación) lleva la llave del equipo en el header
`X-API-Key`. Cada llave tiene un rol (`inventario`, `fabricacion` o `notificaciones`) y solo puede
emitir los tipos de su rol. Una llave enviada en la URL o en el cuerpo se ignora. Las llaves las
entrega Notificaciones por un canal privado y se guardan solo como hash.

## Convenciones

- JSON en `camelCase`; fechas en UTC con formato ISO 8601.
- Un evento `DETECTADA` repetido mientras la alerta sigue activa **no** crea otra notificación:
  responde `200` con el id existente y `duplicada: true`. Es seguro reintentar.
- Errores: `401` y `403` responden `{"mensaje": "Acceso denegado"}`; `422` lista los campos con
  problema; `500` no expone detalles internos.
- Los mensajes de error no cambian entre versiones menores: puede comparar contra ellos.

## Entrega al equipo destino

Cada notificación se publica en una cola interna y se entrega por **webhook** a la URL que el
equipo registre (ver `webhooks` y HU-NOT-16/17). Desde el Sprint 3 las entregas llevan firma
HMAC; el receptor debe ignorar las repetidas usando `X-Notification-Id`.
""".strip()

ETIQUETAS: list[dict[str, str]] = [
    {
        "name": "notificaciones",
        "description": "Eventos que reportan Inventario y Fabricación (llave del rol emisor).",
    },
    {
        "name": "administración",
        "description": "Uso interno de Notificaciones (llave del rol `notificaciones`).",
    },
    {"name": "health", "description": "Estado del proceso. No requiere llave."},
]

CONTACTO = {"name": "Equipo 5 · Notificaciones (Desarrollo de Software II)"}

_EJEMPLO_422: dict[str, Any] = {
    "mensaje": "Los datos enviados no cumplen las reglas establecidas",
    "errores": [{"campo": "stockActual", "error": "Input should be greater than or equal to 0"}],
}


def _error(descripcion: str, mensaje: str) -> dict[str, Any]:
    return {
        "model": ErrorResponse,
        "description": descripcion,
        "content": {"application/json": {"example": {"mensaje": mensaje}}},
    }


_RESPUESTAS: dict[int, dict[str, Any]] = {
    401: _error("Llave ausente, vacía, inválida o desactivada", "Acceso denegado"),
    403: _error("La llave es válida pero su rol no puede hacer esta operación", "Acceso denegado"),
    422: {
        "model": ErrorValidacionResponse,
        "description": "Los datos no cumplen las reglas; `errores` indica cada campo",
        "content": {"application/json": {"example": _EJEMPLO_422}},
    },
    500: _error("Falla interna; no se guardó nada a medias", "Error interno, intente de nuevo"),
}


def respuestas(*codigos: int) -> dict[int | str, dict[str, Any]]:
    """Respuestas de error comunes por código, para el parámetro `responses` de una ruta."""
    return {codigo: _RESPUESTAS[codigo] for codigo in codigos}


def id_operacion(ruta: APIRoute) -> str:
    """crear_notificacion -> crearNotificacion: estable y legible en los clientes generados."""
    primero, *resto = ruta.name.split("_")
    return primero + "".join(parte.capitalize() for parte in resto)

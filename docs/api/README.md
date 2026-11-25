# Contrato de la API de Notificaciones

Para los equipos de **Inventario** y **Fabricación** (y cualquiera que integre con Notificaciones).

- Contrato: [`openapi.json`](openapi.json) (OpenAPI 3.1). Se genera del código y una prueba falla si
  queda desactualizado: `uv run python -m scripts.exportar_openapi`.
- Documentación interactiva: `/docs` (Swagger UI) y `/redoc` en el servidor.
- Versión actual del contrato: **0.2.0**.

Impórtelo en Swagger Editor, Postman o Insomnia, o genere un cliente con `openapi-generator`.

## Lo mínimo para integrar

1. **Pida su llave** al equipo de Notificaciones. Llega por un canal privado y se muestra una sola
   vez. Su rol (`inventario` o `fabricacion`) define qué tipos puede emitir.
2. **Envíe eventos** a `POST /notificaciones` con el header `X-API-Key`:

   ```bash
   curl -X POST http://localhost:8090/notificaciones \
     -H "X-API-Key: $LLAVE" -H "Content-Type: application/json" \
     -d '{"tipo":"STOCK_BAJO_INSUMO","evento":"DETECTADA","productoId":"INS-001",
          "nombre":"Acero inoxidable 304","stockActual":4,"stockMinimo":10}'
   ```

   | Respuesta | Significado |
   |---|---|
   | `201` | Notificación registrada y alerta activada |
   | `200` + `duplicada: true` | Ya había una alerta activa: no se crea otra. Es seguro reintentar |
   | `200` «Alerta resuelta correctamente» | Llegó `REPUESTO` o `RESUELTA` y se cerró la alerta |
   | `401` | Llave ausente, inválida o desactivada |
   | `403` | La llave es válida pero su rol no emite ese tipo |
   | `422` | Datos inválidos; `errores` lista cada campo |

3. **Cuando el artículo se reponga**, envíe el mismo cuerpo con `"evento": "REPUESTO"`. Un nuevo
   `DETECTADA` volverá a notificar.
4. **Reciba las notificaciones** en una URL HTTPS propia (el webhook, abajo).

## Webhook de entrega (HU-NOT-17, Sprint 3)

Notificaciones hará un `POST` a la URL que su equipo registre, con los headers
`X-Notification-Id`, `X-Timestamp` y `X-Signature`, y espera hasta 10 s. Responda **cualquier 2xx**
para confirmar; si no, se reintenta a los 5 minutos hasta 3 veces. La entrega es *al menos una vez*:
ignore las repetidas con `X-Notification-Id`.

La firma es `HMAC-SHA256(secreto, "<X-Timestamp>.<cuerpo crudo>")` en hexadecimal. Ejemplo de receptor
en Python:

```python
import hashlib, hmac, time
from datetime import datetime


def firma_valida(secreto: str, timestamp: str, cuerpo: bytes, firma: str) -> bool:
    antiguedad = time.time() - datetime.fromisoformat(timestamp).timestamp()
    if abs(antiguedad) > 300:  # rechaza mensajes de más de 5 minutos
        return False
    esperada = hmac.new(secreto.encode(), timestamp.encode() + b"." + cuerpo, hashlib.sha256)
    return hmac.compare_digest(esperada.hexdigest(), firma)
```

El cuerpo trae `id`, `tipo`, `equipoEmisor`, `equipoDestino`, `fechaRegistro`, `mensaje` y `datos`
(ver `NotificacionEntregada` en el contrato).

## Estado de cada endpoint

| Endpoint | Historia | Estado |
|---|---|---|
| `POST /notificaciones` (stock bajo, resolver alertas) | HU-NOT-01, HU-NOT-02 | Disponible |
| `POST /notificaciones/ciclo` (solo administración) | HU-NOT-02 | Disponible |
| Webhook de entrega | HU-NOT-17 | Contrato publicado; entrega en el Sprint 3 |
| `CONDICION_URGENTE` | HU-NOT-05 | Sprint 2 |
| `GET /notificaciones/estado`, filtros, detalle y marcar leída | HU-NOT-07 a 10 | Sprints 2 y 3 |
| Destinatarios y URL del callback | HU-NOT-13 a 16 | Sprints 2 y 3 |

## Cómo se versiona

- Cambios compatibles (endpoints nuevos, campos opcionales nuevos): sube la versión **menor**.
- Cambios que rompen (quitar o renombrar campos, cambiar códigos o mensajes): sube la **mayor** y se
  avisa a los equipos antes.
- Toda HU que cambie la API debe regenerar `openapi.json` y subir `API_VERSION` en
  `app/api/contrato.py`.

## Para quien agrega un endpoint

Use `respuestas(401, 403, 422, 500)` de `app/api/contrato.py`, ponga `summary`, `description` y
`tags`, describa los campos con `Field(description=...)` y agregue ejemplos. `tests/unit/test_openapi.py`
falla si falta algo.

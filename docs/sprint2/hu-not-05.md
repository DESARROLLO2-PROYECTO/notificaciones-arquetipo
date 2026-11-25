# HU-NOT-05 Reportar una condición urgente

Responsable: Sebastián Rubio, rama `srubio`.

La API de Fabricación reporta una condición urgente con `POST /notificaciones` y tipo
`CONDICION_URGENTE`. Reutiliza el flujo de alertas (HU-NOT-02) y la publicación (HU-NOT-03).

## Tareas técnicas

| Tarea | Trabajo | Evidencia |
|---|---|---|
| TS-05-01 | Sembrar el tipo | Migración `0006_tipo_condicion_urgente`: emisor y destino `fabricacion`, clave `codigoCondicion`, TTL 60 min |
| TS-05-02 | Validar el cuerpo | `CondicionUrgenteRequest` en `app/api/schemas.py`; `CrearNotificacionBody` elige el modelo según `tipo` |
| TS-05-03 | Clave de alerta del catálogo | `ServicioNotificaciones` toma la clave de `campo_clave` del tipo, ya no de `productoId` |
| TS-05-04 | Mensajes de respuesta | Router (duplicada "para esta condición") y `_error_validacion` (422 propio) |
| TS-05-05 | Pruebas y documentación | Pruebas unitarias, de integración (RabbitMQ real) y OpenAPI en `/docs` |

## Criterios de aceptación

| Criterio del backlog | Comportamiento implementado |
|---|---|
| 1. Registro | Con API Key de `fabricacion`: `codigoCondicion` (1 a 30, letras, números y guion), `descripcion` (1 a 100, no vacía) y `evento` (por defecto `DETECTADA`). Sin alerta activa se guarda la notificación con esos datos en el payload (sin `mensaje`, que se calcula, máx. 200) y se activa la alerta por `codigoCondicion`. |
| 2. Respuesta | 201 con `id` y "Notificación registrada correctamente". |
| 3. Duplicada | Con alerta activa no se crea nada: 200 con el `id` original, `duplicada` true y "Ya existe una alerta activa para esta condición". |
| 4. Resolución | `RESUELTA` o `REPUESTO` con el mismo `codigoCondicion`, o la expiración (60 min), resuelven según HU-NOT-02; una nueva `DETECTADA` registra otra. |
| 5. Datos inválidos | 422 "Información de la condición urgente incompleta o inválida" con la lista `errores` de siempre. |
| 6. Sin catálogo de condiciones | Se registra lo enviado. |
| 7. Falla interna | 500 "No fue posible registrar la notificación, intente de nuevo", sin datos parciales. |
| 8. Publicación | Va a la cola `notif.fabricacion` como cualquier notificación nueva. |

Una llave de otro rol (por ejemplo `inventario`) recibe 403: el emisor se valida contra el tipo.
Un `tipo` desconocido sigue respondiendo 422 con los errores del cuerpo de stock bajo.

## Verificación

```bash
uv run pytest --cov=app
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports
```

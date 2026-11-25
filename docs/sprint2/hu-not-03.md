# HU-NOT-03 Publicar cada notificación registrada en el broker

Responsable: Sebastián Rubio, rama `srubio`.

Cada notificación nueva se publica en la cola de su destino justo después de registrarse. Si el
broker no responde, queda pendiente y el ciclo interno la reintenta. Base técnica en
`docs/sprint2/cola.md`.

## Tareas técnicas

| Tarea | Trabajo | Evidencia |
|---|---|---|
| TS-03-01 | Marcar y contar publicaciones | `NotificacionRepo.marcar_publicada`, `registrar_fallo_publicacion` (incremento atómico) |
| TS-03-02 | Publicar al registrar | `ServicioNotificaciones._publicar_nueva`, tras el commit del registro |
| TS-03-03 | Reintentar pendientes | `NotificacionRepo.tomar_pendientes_publicacion` y tarea `publicaciones` del ciclo |
| TS-03-04 | Inyectar el publicador | `app/api/deps.py` resuelve `obtener_publicador()` al publicar |
| TS-03-05 | Pruebas y documentación | Pruebas unitarias, de integración (RabbitMQ real) y OpenAPI en `/docs` |

No hay migración: las columnas ya existían.

## Criterios de aceptación

| Criterio del backlog | Comportamiento implementado |
|---|---|
| 1. Publicación en menos de 1 min | La solicitud que registra publica de inmediato; si falla, el ciclo (cada 5 min) la toma cuando tiene más de 1 min. El mensaje solo lleva `id` y `tipo`. |
| 2. Una cola por destino | Clave de ruteo igual al destino; cola `notif.<destino>`. |
| 3. Credenciales del broker | Solo la API y el worker tienen `AMQP_URL`; el emisor nunca la ve. |
| 4. Tras publicar | `publicada_at` en UTC, `proximo_intento_entrega = publicada_at + 5 min` y el log `Notificación <id> publicada correctamente` (después del commit). |
| 5. Una sola vez | Con `publicada_at` no se vuelve a publicar: ni duplicadas, ni resoluciones, ni el ciclo. |
| 6. Cola no disponible | La notificación se conserva: `intentos_publicacion` +1, `ultimo_error_publicacion` con el tipo de error (nunca la URL) y el log `Cola no disponible, la notificación <id> queda pendiente de publicación`. La solicitud sigue respondiendo 201. Sin `AMQP_URL` ocurre lo mismo. |
| 7. Reintento | El ciclo toma las pendientes con menos de 3 intentos y más de 1 min, en orden de creación (hasta 50 por ciclo; si el broker falla se detiene en la primera, el resto espera al siguiente ciclo), con `FOR UPDATE SKIP LOCKED`: dos ciclos simultáneos no toman la misma. |
| 8. Tres intentos fallidos | Log `La notificación <id> no pudo publicarse tras 3 intentos`; deja de reintentarse y queda para revisión manual. El estado `publicacion_fallida` se calcula (`publicada_at` nulo e `intentos_publicacion` = 3), no se guarda. |

`POST /notificaciones/ciclo` responde ahora `{"alertasCerradas": N, "publicadas": M, "errores": []}`.

Si el proceso cae entre publicar y confirmar la marca en la base, el mensaje puede repetirse
(entrega al menos una vez): el worker debe tolerar duplicados por `id`.

## Verificación

```bash
uv run pytest --cov=app
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports
```

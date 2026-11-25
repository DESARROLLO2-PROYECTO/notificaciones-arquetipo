# HU-NOT-02 Resolver las alertas activas

Responsable: Sebastián Rubio, rama `srubio`.

Una alerta activa se cierra cuando el emisor avisa que el stock se repuso (`REPUESTO` o
`RESUELTA`) o cuando vence su tiempo de vida. Cerrada la alerta, una nueva `DETECTADA`
registra otra notificación.

## Tareas técnicas

| Tarea | Trabajo | Evidencia |
|---|---|---|
| TS-02-01 | Guardar la fecha de resolución | Migración `0005`, `Alerta.cerrada_at` en el modelo y en `puertos.Alerta` |
| TS-02-02 | Resolver por evento del emisor | `ServicioNotificaciones._resolver_alerta`; `AlertaRepo.resolver` |
| TS-02-03 | Expirar alertas vencidas | `AlertaRepo.expirar_vencidas`: un solo `UPDATE ... RETURNING` |
| TS-02-04 | Ciclo de limpieza | `ServicioNotificaciones.ejecutar_ciclo` y `POST /notificaciones/ciclo` |
| TS-02-05 | Pruebas y documentación | Pruebas unitarias, de integración y OpenAPI en `/docs` |

## Criterios de aceptación

| Criterio del backlog | Comportamiento implementado |
|---|---|
| 1. Resolución por el emisor | `REPUESTO`/`RESUELTA` con alerta activa: motivo `EMISOR`, `cerrada_at` en UTC, notificación original intacta. HTTP 200 `Alerta resuelta correctamente`. |
| 2. Sin alerta activa | No cambia datos. HTTP 200 `No había una alerta activa`. |
| 3. Nueva detección tras resolver | Sin alerta activa, `DETECTADA` registra una notificación nueva (201). |
| 4. Vencimiento por tipo | `expira_at` se calcula al crear con `ttl_alerta_min` del tipo (1440 sembrado); reenviar no lo renueva. |
| 5. Vencida sin limpiar | `DETECTADA` marca antes `EXPIRACION` la vencida del mismo tipo y clave y registra la nueva en la misma transacción (el índice único parcial solo admite una activa). |
| 6. Ciclo | `POST /notificaciones/ciclo` solo con llave del rol `notificaciones` (otro rol: 403; sin llave: 401). Cierra las vencidas y registra `Limpieza de alertas completada: N alertas expiradas`. Cada tarea del ciclo se aísla: si una falla se registra y las demás siguen. |
| 7. Ciclos simultáneos | El cierre es un único `UPDATE ... WHERE cerrada_at IS NULL AND expira_at <= ahora RETURNING`; ningún registro se procesa dos veces. Respuesta `{"alertasCerradas": N, "errores": []}`; `errores` lista las tareas que fallaron. |
| 8. Cambio de TTL | Solo afecta a alertas nuevas: el vencimiento queda guardado en cada alerta. |
| 9. Registro de la resolución | `Alerta <tipo>/<clave> resuelta por <EMISOR\|EXPIRACION> notificacion_id=<uuid>`. |

## Cómo probarlo

Con la API y PostgreSQL iniciados y las llaves de `inventario` y `notificaciones` creadas
(ver HU-NOT-11):

```bash
curl -X POST localhost:8000/notificaciones -H "X-API-Key: $LLAVE_INVENTARIO" \
  -H "Content-Type: application/json" \
  -d '{"tipo":"STOCK_BAJO_INSUMO","evento":"DETECTADA","productoId":"INS-1","nombre":"Acero","stockActual":2,"stockMinimo":10}'

curl -X POST localhost:8000/notificaciones -H "X-API-Key: $LLAVE_INVENTARIO" \
  -H "Content-Type: application/json" \
  -d '{"tipo":"STOCK_BAJO_INSUMO","evento":"REPUESTO","productoId":"INS-1","nombre":"Acero","stockActual":2,"stockMinimo":10}'
```

El primero responde 201; el segundo 200 `Alerta resuelta correctamente`.

El ciclo lo invoca un proceso externo y periódico (por ejemplo, cron cada 5 minutos):

```bash
*/5 * * * * curl -s -X POST http://localhost:8000/notificaciones/ciclo -H "X-API-Key: $LLAVE_NOTIFICACIONES"
```

## Verificación

```bash
uv run pytest --cov=app
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run lint-imports
```

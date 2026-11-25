# Modelo de datos y el ER del DAS

El esquema de PostgreSQL sigue el diagrama «04 Modelo entidad-relación» del DAS. La migración
`0007_alineacion_er` lo deja igual al diagrama en las tablas ya implementadas, y
`tests/integration/test_er.py` lo comprueba (tipos, obligatoriedad, índices y restricciones).

| Tabla | Estado | Historia |
|---|---|---|
| `equipos`, `api_keys` | Implementadas | HU-NOT-11 y 12 |
| `tipos_notificacion`, `notificaciones`, `alertas` | Implementadas | HU-NOT-01, 02, 03 y 05 |
| `destinatarios`, `destinatario_tipos` | Pendientes | HU-NOT-13 a 15 |
| `envios_correo` | Pendiente | HU-NOT-04 |
| `callbacks` | Pendiente | HU-NOT-16 y 17 |

Las tablas pendientes deben crearse **con los nombres y columnas exactos del diagrama**, y cada
una agrega su bloque a `ER` en `test_er.py`.

## Decisiones donde el código completa al diagrama

- **Tipos sin campo clave:** `tipos_notificacion.campo_clave` es opcional. Un tipo sin clave
  (por ejemplo `ACUMULACION_PEDIDOS`) tiene una sola alerta, con la clave `-`.
- **Toda alerta vence:** `alertas.expira_at` es obligatoria, por lo que el TTL del tipo debe ser
  de al menos 1 minuto (`ck_tipos_ttl_positivo`).
- **Alerta activa = `cerrada_at IS NULL`.** El índice único parcial `(tipo, clave)` usa ese
  predicado, y `ck_alertas_cierre_coherente` obliga a que `cerrada_at` y `motivo_resolucion`
  estén los dos vacíos o los dos llenos. El motivo es `EMISOR` o `EXPIRACION`.
- **Índices de `notificaciones`:** `creada_at`, `tipo` y `equipo_destino_id`, para el listado
  paginado de HU-NOT-07 (el DAS promete 2 s). Si esa consulta lo necesita, un índice compuesto
  `(equipo_destino_id, creada_at)` se agrega en su migración.
- **`entregada_at`:** existe y la usará HU-NOT-17 para el estado `entregada`.

## Al agregar migraciones en paralelo

Una sola cabeza de Alembic (la guarda está en `tests/unit/test_migraciones.py`). Quien mergee
segundo cambia el `down_revision` de su migración a la cabeza actual.

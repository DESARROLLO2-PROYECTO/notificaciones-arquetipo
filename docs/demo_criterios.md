# Demo técnica por criterios de aceptación

Para el sprint review: `python -m scripts.demo.criterios` recorre una historia **criterio por
criterio**. Cada criterio muestra su texto del backlog, un comando de ejemplo (curl o consola) que
se puede copiar y pegar, la respuesta real del servicio y la evidencia en la base de datos o en los
registros. Termina con un resumen de ✓ y ✗. Es distinto de `docs/demo.md`, que cuenta un recorrido
de equipos falsos; este va por los criterios de cada historia.

## Preparación local

```bash
cp .env.example .env
docker compose up --build -d              # API, PostgreSQL y RabbitMQ
uv run python -m scripts.demo.criterios --hu 11 --preparar   # crea las llaves en .demo.env y corre
```

Para copiar los `curl` que muestra la demo, en otra terminal:

```bash
set -a; source .demo.env; set +a          # DEMO_LLAVE_INVENTARIO, DEMO_LLAVE_FABRICACION, ...
export DEMO_URL=http://localhost:8090
```

## Uso

```bash
uv run python -m scripts.demo.criterios --hu 11                 # HU-NOT-11: generar y desactivar API Keys
uv run python -m scripts.demo.criterios --hu 01                 # HU-NOT-01: reportar stock bajo
uv run python -m scripts.demo.criterios --hu todas              # las dos, una tras otra
uv run python -m scripts.demo.criterios --hu 01 --solo 3,6      # solo los criterios 3 y 6
```

Con pausas (Enter para avanzar) por defecto; `--rapido` las quita. La dirección se cambia con
`--url` o `DEMO_URL`, igual que en la otra demo. Otras opciones: `--sin-color`, `--conservar`
(HU-11: no desactivar las llaves que crea la demo), `--sin-parar-bd` (HU-01 criterio 7: no apagar
la base de datos) y `--hilos N` (HU-01 criterio 6: solicitudes simultáneas, 10 por defecto).

La evidencia en la base de datos y los registros usa `docker compose` en la carpeta actual: sirve
con la API local. Contra otra IP la demo funciona, pero omite esas partes y lo dice. La HU-11
necesita el `docker compose` local porque se demuestra con las herramientas de consola del servicio.

## HU-NOT-11: generar y desactivar API Keys

| Criterio | Qué se hace | Qué se comprueba |
|---|---|---|
| 1. Generación | `crear_api_key --rol inventario` | ID y llave una sola vez; 32 bytes; en la base solo el SHA-256, el rol, la fecha y `activa` |
| 2. Rol inválido | `crear_api_key --rol marciano` | "Rol no válido" y ninguna fila nueva |
| 3. Máximo dos activas | Se crea hasta tener dos y una tercera | "Ya existen dos llaves activas para este rol" |
| 4. Desactivación | La llave entra (200), se desactiva, ya no entra (401), se rota | El registro se conserva con `activa=f` y se libera un cupo |
| 5. Sin secretos | Búsqueda de las llaves completas | 0 coincidencias en los registros y en la tabla `api_keys` |
| 6. Llave administrativa | La llave `notificaciones` ejecuta el ciclo | 200 con la llave de administración y 403 con la de otro rol |

Las llaves que crea la demo se desactivan al terminar, así que no consume cupos de los roles. El
comando `listar_api_keys` (`docker compose exec -T api python -m scripts.listar_api_keys`) muestra
las llaves con ID, rol, prefijo y estado, nunca su valor.

## HU-NOT-01: reportar stock bajo

| Criterio | Qué se hace | Qué se comprueba |
|---|---|---|
| 1. Registro | `POST /notificaciones` con stock bajo (insumo y producto) | UUID, destino por tipo, datos guardados sin el mensaje, alerta activa |
| 2. Respuesta 201 | La misma solicitud | 201 y "Notificación registrada correctamente" |
| 3. Duplicado | Se repite el evento | 200, `duplicada`, mismo id, una sola notificación en la base |
| 4. Datos inválidos | 16 solicitudes mal formadas | 422, el mensaje y los campos con error; nada se registra |
| 5. Forma, no verdad | `stockActual` mayor que `stockMinimo` | Se procesa igual (201) |
| 6. Concurrencia | 10 solicitudes simultáneas | Una responde 201 y nueve 200 con el mismo id; una notificación y una alerta |
| 7. Falla interna | Se apaga la base de datos un momento | 500 con el mensaje controlado; nada a medias; el servicio se recupera |
| 8. Registro | Cuatro eventos del mismo artículo | `REGISTRADA`, `ALERTA_YA_ACTIVA`, `RECHAZADA` y `ALERTA_CERRADA` con tipo, destino, clave e id |

El criterio 7 apaga y enciende `db` con `docker compose stop db` y `start db`. Para saltarlo,
`--sin-parar-bd`; la prueba automática `test_falla_interna_500` también lo cubre.

## Cómo se mantiene al día

`tests/integration/test_demo_criterios.py` ejecuta las dos historias completas contra Postgres real,
con las herramientas de consola y el SQL resueltos en proceso. Si el servicio cambia y un criterio
deja de cumplirse, el CI lo avisa. Para sumar otra historia, se agrega una función en
`scripts/demo/criterios.py` y se registra en `HISTORIAS`.

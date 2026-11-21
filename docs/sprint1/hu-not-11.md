# HU-NOT-11 Generar y desactivar API Keys

Responsable: Juan José Rodríguez, rama `jrodriguez`.

Historia del sprint 1 en la hoja `Planeación` del backlog `20261021_PB_Notificaciones.xlsx`:
como administrador de Notificaciones, generar una API Key para un servicio para que pueda
autenticarse con un rol definido. Estimación del backlog: 3 puntos.

Esta implementación administra las credenciales por consola. HU-NOT-12 utilizará esas
credenciales para autenticar y autorizar solicitudes HTTP. Los endpoints actuales todavía
son públicos; el ciclo de notificaciones tampoco existe aún.

## Tareas técnicas

Una HU describe un resultado para su usuario; las tareas técnicas (TS) describen el trabajo
necesario para conseguirlo. No son historias nuevas ni puntos adicionales al backlog.

| Tarea | Trabajo | Evidencia |
|---|---|---|
| TS-11-01 | Persistir API Keys y preparar los tres roles | Modelo `ApiKey`, migración `0002` y `ApiKeyRepo` |
| TS-11-02 | Generar, limitar a dos activas y desactivar | `ApiKeyService`; bloqueo por equipo durante la generación |
| TS-11-03 | Proporcionar el script de administración | `python -m app.cli.api_keys`; salida tras el commit |
| TS-11-04 | Comprobar criterios y documentar uso | Pruebas unitarias y de integración con PostgreSQL |

## Criterios de aceptación

| Criterio del backlog | Comportamiento implementado |
|---|---|
| 1. Generación | `secrets.token_urlsafe(32)` usa 32 bytes aleatorios; persiste hash SHA-256, equipo/rol, fecha UTC, estado activo y prefijo de identificación del ER. Muestra ID y llave completa una vez, tras confirmar la transacción. |
| 2. Rol inválido | Solo admite `inventario`, `fabricacion` y `notificaciones`. Devuelve `Rol no válido` sin conectarse a la BD. |
| 3. Máximo dos activas | Bloquea la fila del equipo con `FOR UPDATE`, cuenta llaves activas y rechaza una tercera con `Ya existen dos llaves activas para este rol`. |
| 4. Desactivación | Conserva el registro y marca `activa=false`; repetir la desactivación no falla. La búsqueda de llaves activas excluye las desactivadas. La aplicación de este estado en HTTP depende de HU-NOT-12. |
| 5. No guardar secretos | El valor completo no llega al repositorio ni se registra en logs. Los errores de consola no muestran excepciones de conexión ni parámetros SQL. |
| 6. Primera llave administrativa | Permite crear la primera llave de `notificaciones` sin requerir otra llave. Queda disponible para HU-NOT-12 y el ciclo de HU-NOT-02. |

El límite se garantiza para las generaciones hechas mediante este servicio, incluso desde
procesos concurrentes. Las herramientas que generen llaves en el futuro deben reutilizarlo.
No hay endpoint de creación, listado de secretos ni recuperación de llaves completas.

## Preparación y demostración

Con la API y PostgreSQL iniciados mediante `docker compose up --build -d`, el contenedor
aplica las migraciones al arrancar. Ejecutar desde la raíz del repositorio:

```bash
docker compose exec api python -m app.cli.api_keys generar --rol inventario
docker compose exec api python -m app.cli.api_keys generar --rol inventario
docker compose exec api python -m app.cli.api_keys generar --rol inventario
```

Las primeras dos operaciones muestran sus respectivos identificadores y llaves; la tercera
falla por el límite. Guardar cada llave al crearla y entregarla por un canal privado.
La salida de generación contiene la credencial: no adjuntarla a evidencias, commits ni PR.

Usar el ID devuelto por la primera operación para desactivarla (reemplazar `<id>`):

```bash
docker compose exec api python -m app.cli.api_keys desactivar --id <id>
docker compose exec api python -m app.cli.api_keys generar --rol inventario
docker compose exec api python -m app.cli.api_keys generar --rol notificaciones
```

Desactivar libera un cupo del rol; la otra llave de Inventario permanece activa. La última
operación crea la llave administrativa. No requiere un servicio de correo ni un broker.

Sin contenedores para la aplicación, configurar `DATABASE_URL` para un PostgreSQL accesible
desde el equipo y ejecutar:

```bash
uv sync --frozen
uv run alembic upgrade head
uv run python -m app.cli.api_keys generar --rol inventario
uv run python -m app.cli.api_keys desactivar --id <id>
```

La dirección `db` del `.env.example` solo funciona dentro de la red de Docker Compose.
Los códigos de salida son 0 para éxito, 1 para error de operación y 2 para argumentos
incorrectos. Un identificador inexistente devuelve `API Key no encontrada`.

## Migración y coordinación

`0002_api_keys.py` crea la tabla e índice de llaves y agrega los equipos `inventario`,
`fabricacion` y `notificaciones` si faltan. Conserva los equipos preexistentes y no crea
credenciales automáticamente. Al revertir `0002`, elimina las llaves pero conserva equipos,
ya que podrían existir antes o tener otros usos. Revertir elimina credenciales: usarlo
únicamente como operación explícita de administración, no como parte de la demostración.

HU-NOT-12 debe calcular el hash del header recibido y usar
`ApiKeyRepo.obtener_activa_por_hash()` para descartar llaves inválidas o desactivadas; luego
debe obtener el rol del equipo y aplicar sus reglas de autorización. Nunca debe buscar solo
por prefijo ni aceptar llaves inactivas. Las migraciones siguientes deben partir de `0002`.

## Verificación

```bash
uv run pytest tests/unit
uv run pytest --cov=app --cov-report=term-missing --cov-fail-under=80
uv run coverage report --include='app/domain/*,app/api/schemas.py' --fail-under=100
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run lint-imports
docker build -t notificaciones:hu-not-11 .
```

La integración usa una base PostgreSQL desechable mediante testcontainers; no modifica la
base configurada por el desarrollador. Comprueba el script en procesos reales, persistencia
sin secretos completos, rotación, rollback, migración reversible y cinco generaciones
concurrentes del mismo rol (solo dos deben prosperar). En CI no se permite omitir estas pruebas
si PostgreSQL falla al arrancar.

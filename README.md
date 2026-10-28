# Notificaciones

## 1. Qué es

Arquetipo mínimo de un servicio REST en FastAPI con capas estrictas `app/api` → `app/domain` ←
`app/infrastructure`, más `app/security` (validación Pydantic). El dominio define puertos
(Protocols) y la infraestructura los implementa con SQLAlchemy 2 sobre PostgreSQL 16; una
transacción por solicitud (commit al final, rollback ante error). Incluye un único flujo
transaccional sobre la entidad `Equipo` (tabla `equipos` del ER del DAS) y ninguna HU.

## 2. Prerrequisitos

- Docker 29
- Docker Compose v2 o superior
- uv 0.13
- Python 3.12 (uv lo descarga si falta)

## 3. Quick start

```bash
git clone <URL_DEL_REPO> arquetipo && cd arquetipo
cp .env.example .env          # cambia las claves de ejemplo
docker compose up --build
```

En otra terminal:

```bash
curl -i -X POST http://localhost:8000/equipos \
  -H "Content-Type: application/json" -d '{"nombre":"inventario","esAdmin":false}'
curl -i http://localhost:8000/equipos/1
```

Swagger en http://localhost:8000/docs. Errores: 404 (no existe), 409 (nombre repetido), 422 (datos inválidos).

## 4. Tests locales

```bash
uv sync
uv run pytest                    # unitarios + integración
uv run pytest tests/unit         # solo unitarios (sin BD ni Docker)
```

La integración usa testcontainers con `postgres:16.15-alpine` y requiere Docker; sin él se omite.

## 5. Cobertura

```bash
uv run pytest --cov=app --cov-report=term-missing --cov-report=html   # global >= 80 %
uv run coverage report --include='app/domain/*,app/security/*' --fail-under=100
```

El reporte HTML queda en `htmlcov/index.html`.

## 6. Estructura

Anotada en [`docs/arquetipo/02_blueprint.md`](docs/arquetipo/02_blueprint.md).

```
app/main.py            bootstrap, routers y manejadores de error
app/config.py          DATABASE_URL y LOG_LEVEL (pydantic-settings)
app/api/               deps.py (sesión → repo → servicio), equipos.py, health.py
app/security/          schemas.py (EquipoIn / EquipoOut)
app/domain/            puertos.py, errores.py, equipo_service.py
app/infrastructure/    db.py, models.py, repositories.py
migrations/            Alembic; 0001 crea la tabla equipos
tests/unit | integration
```

## 7. Decisiones de arquitectura

Detalle en [`docs/arquetipo/01_validacion.md`](docs/arquetipo/01_validacion.md).

- Multicapa estricta (DAS): `api` → `domain` ← `infrastructure`, con `security` para validar.
- Inyección de dependencias con `Depends`; `api/deps.py` es la raíz de composición.
- El dominio define puertos (`Protocol`) y no importa FastAPI ni SQLAlchemy.
- Una transacción por solicitud: commit al final y rollback ante error.
- Docker multi-stage, imagen con versión fija y usuario no root.

Para añadir una entidad, copia el patrón de `Equipo`: modelo y migración, puerto, servicio,
repositorio, DTO, `deps.py` y router (registrado en `main.py`), con su test unitario con fake del
puerto y su test de integración.

## 8. Limitaciones y siguientes pasos

Limitaciones:

- Las migraciones corren en el `CMD` del contenedor: válido con una sola réplica.
- Sin TLS: la API escucha en el 8000 y el DAS prevé el 443.
- Sin autenticación: los endpoints son públicos.

Siguientes pasos:

- Resto de tablas del ER.
- API Key.
- Worker, Scheduler, Publisher y Mailer.
- Monitoreo: /metrics con Prometheus y Grafana.
- CI/CD.

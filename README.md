# Notificaciones

## 1. Qué es

Arquetipo mínimo de un servicio REST en FastAPI con capas estrictas `app/api` → `app/domain` ←
`app/infrastructure`; la validación Pydantic (DTO) vive en `app/api/schemas.py`. El dominio define puertos
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
curl -i -X POST http://localhost:8090/equipos \
  -H "Content-Type: application/json" -d '{"nombre":"inventario","esAdmin":false}'
curl -i http://localhost:8090/equipos/1
```

El puerto publicado es el 8090 (`API_PORT` en `.env`); dentro del contenedor la API escucha en el 8000.
Swagger en http://localhost:8090/docs. Errores: 404 (no existe), 409 (nombre repetido), 422 (datos inválidos).

## 4. Tests locales

```bash
uv sync
uv run pytest                    # unitarios + integración
uv run pytest tests/unit         # solo unitarios (sin BD ni Docker)
```

La integración usa testcontainers con `postgres:16.15-alpine` y requiere Docker; sin él se omite en local, pero en CI el arranque fallido de Postgres rompe el build.

## 5. Cobertura

```bash
uv run pytest --cov=app --cov-report=term-missing --cov-report=html --cov-fail-under=80   # falla si global < 80 %
uv run coverage report --include='app/domain/*,app/api/schemas.py' --fail-under=100
```

El reporte HTML queda en `htmlcov/index.html`.

## 6. Integración continua

[![CI](https://github.com/DESARROLLO2-PROYECTO/notificaciones-arquetipo/actions/workflows/ci.yml/badge.svg)](https://github.com/DESARROLLO2-PROYECTO/notificaciones-arquetipo/actions/workflows/ci.yml)

`.github/workflows/ci.yml` corre en push a cualquier rama y en pull requests a `develop` y `main`. Los pasos
van en orden y el primero que falla detiene el resto: pruebas unitarias, cobertura (global >= 80 % y 100 % en
domain/schemas), ruff + mypy + import-linter (`uv run lint-imports`), build de la imagen Docker, publicación en Docker Hub y análisis en SonarCloud. El resultado se ve en la
pestaña Actions del repositorio.

SonarCloud requiere el proyecto creado en sonarcloud.io (repo público), el secret `SONAR_TOKEN` y la variable
de repo `SONAR_ENABLED=true`; sin la variable el paso se omite y el resto del pipeline sigue igual. El token solo
lo ve el paso de Sonar, y un quality gate en rojo hace fallar el CI (`sonar.qualitygate.wait=true`).

Docker Hub publica la imagen (`<usuario>/notificaciones:<sha>` y `:<rama>`) solo en push a `develop` o `main` y
con la variable de repo `DOCKERHUB_ENABLED=true`; sin ella el paso se omite. Crear la variable `DOCKERHUB_ENABLED`
y los secrets `DOCKERHUB_USERNAME` y `DOCKERHUB_TOKEN` (token de acceso de Docker Hub). Solo ese paso los ve.

## 7. Estructura

Anotada en [`docs/arquetipo/02_blueprint.md`](docs/arquetipo/02_blueprint.md).

```
app/main.py            bootstrap, routers y manejadores de error
app/config.py          DATABASE_URL y LOG_LEVEL (pydantic-settings)
app/api/               deps.py (sesión → repo → servicio), schemas.py (EquipoIn / EquipoOut)
app/api/routers/       equipos.py, health.py
app/domain/            puertos.py, errores.py, equipo_service.py
app/infrastructure/    db.py, models.py, repositories.py
migrations/            Alembic; 0001 crea la tabla equipos
tests/unit | integration
```

## 8. Decisiones de arquitectura

Detalle en [`docs/arquetipo/01_validacion.md`](docs/arquetipo/01_validacion.md).

- Multicapa estricta (DAS): `api` → `domain` ← `infrastructure`, con la validación Pydantic/DTO en `app/api/schemas.py` (ya no hay capa `security` aparte). `lint-imports` hace cumplir las capas `api` > `infrastructure` > `domain` y que el dominio no importe sqlalchemy, fastapi ni pydantic.
- Inyección de dependencias con `Depends`; `api/deps.py` es la raíz de composición.
- El dominio define puertos (`Protocol`) y no importa FastAPI ni SQLAlchemy.
- Una transacción por solicitud: commit al final y rollback ante error.
- Docker multi-stage, imagen con versión fija y usuario no root.

Para añadir una entidad, copia el patrón de `Equipo`: modelo y migración, puerto, servicio,
repositorio, DTO, `deps.py` y router (registrado en `main.py`), con su test unitario con fake del
puerto y su test de integración.

## 9. Limitaciones y siguientes pasos

Limitaciones:

- Las migraciones corren en el `CMD` del contenedor: válido con una sola réplica.
- Sin TLS: la API escucha en el 8000 y el DAS prevé el 443.
- Sin autenticación: los endpoints son públicos.

Siguientes pasos:

- Resto de tablas del ER.
- API Key.
- Worker, Scheduler, Publisher y Mailer.
- CD.

# Fase 2, paso 2.1: Project Structure Blueprint

Alcance: microservicio de Notificaciones; un único flujo transaccional sobre `Equipo`. Las capas siguen el diagrama lógico del DAS.

```
arquetipo/
├── app/
│   ├── main.py                 Bootstrap, routers y manejadores de error (404/409/422)   [FastAPI]
│   ├── config.py               Configuración externa 12-factor                            [pydantic-settings]
│   ├── api/                    ── VIEW ──
│   │   ├── deps.py             Raíz de composición: sesión → EquipoRepo → EquipoService   [FastAPI Depends]
│   │   ├── equipos.py          Router/Controlador (MVC): POST /equipos, GET /equipos/{id} [FastAPI APIRouter]
│   │   └── health.py           GET /health                                                [FastAPI]
│   ├── security/               ── SECURITY ──
│   │   └── schemas.py          Validator / DTO: EquipoIn, EquipoOut                       [Pydantic v2]
│   ├── domain/                 ── LOGIC ──
│   │   ├── puertos.py          Entidad Equipo + EquipoRepository (Repository, puerto)     [dataclass, Protocol]
│   │   ├── errores.py          ErrorDominio, NoEncontrado, NombreDuplicado                [Python]
│   │   └── equipo_service.py   Service / caso de uso: crear, obtener                      [Python]
│   └── infrastructure/         ── DATA ACCESS ──
│       ├── db.py               Engine y Unit of Work (una transacción por solicitud)      [SQLAlchemy 2]
│       ├── models.py           Modelo ORM Equipo                                          [SQLAlchemy 2]
│       └── repositories.py     EquipoRepo: Repository/DAO (adaptador del puerto)          [SQLAlchemy 2]
├── migrations/                 ── UTILITY ── env.py + 0001_equipos.py                     [Alembic]
├── tests/unit/                 Fake del puerto (AAA) y schemas                            [pytest]
├── tests/integration/          Flujo con Postgres real                                    [testcontainers]
├── Dockerfile, .dockerignore   Multi-stage, usuario no root                               [Docker]
├── docker-compose.yml          db (postgres 16.15) + api, healthchecks, volumen, red      [Compose]
├── .env.example, .gitignore, pyproject.toml, uv.lock, alembic.ini
└── README.md, docs/arquetipo/
```

Sin CI/CD ni API Key: quedan como siguientes pasos (README §8).

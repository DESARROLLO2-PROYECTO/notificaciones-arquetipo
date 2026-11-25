# Despliegue en la EC2

Lo despliega `.github/workflows/cd.yml` cuando el CI de `main` termina bien: copia
`docker-compose.prod.yml` y el `Caddyfile` a `~/notificaciones/`, descarga la imagen del commit,
levanta todo y verifica `/health` (en el servidor y por HTTPS).

## Qué corre

| Servicio | Qué es | Notas |
|---|---|---|
| `db` | PostgreSQL 16 | Volumen `notif_pgdata`. Sin puertos hacia afuera |
| `api` | La API (FastAPI) | Aplica las migraciones al arrancar. Escucha solo en `127.0.0.1:8090` |
| `planificador` | Misma imagen, otro proceso | Cada `CICLO_INTERVALO_S` (300 s) cierra alertas vencidas y reintenta publicaciones pendientes |
| `caddy` | Proxy inverso con HTTPS | Puertos 80 y 443; pide y renueva el certificado (Let's Encrypt). Volumen `caddy_data` |

El broker (CloudAMQP) y el correo son servicios externos: no corren en la EC2.

## `~/notificaciones/.env` (no se sube a git)

El CD se detiene con un aviso si faltan `AMQP_URL`, `DOMINIO` o `CICLO_INTERVALO_S`.

| Variable | Valor |
|---|---|
| `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Base de datos (ya existen) |
| `LOG_LEVEL`, `API_PORT` | `INFO`, `8090` (ya existen) |
| `API_IMAGE` | Lo reescribe el CD con el tag del commit |
| `AMQP_URL` | URL `amqps://...` de CloudAMQP (secreto) |
| `AMQP_TIMEOUT_S` | `10` |
| `CICLO_INTERVALO_S` | `300` |
| `DOMINIO` | `13-59-144-83.sslip.io` (nombre que apunta a la IP del servidor) |

## Antes del primer despliegue con HTTPS

1. **Security group** (`notif-sg`, `us-east-2`): ya tiene reglas de entrada para TCP **80** y
   **443** desde `0.0.0.0/0`. El 80 hace falta para que Let's Encrypt valide el dominio y para
   redirigir a HTTPS. Después del primer despliegue con HTTPS se puede **cerrar el 8090**: la API ya
   solo escucha dentro del servidor.
2. **IP fija**: el dominio `13-59-144-83.sslip.io` resuelve a esa IP, que hoy es una IP pública
   normal: si la instancia se detiene y se inicia, cambia. Una *Elastic IP* la deja fija (cambia la
   IP actual una sola vez: habría que actualizar `DOMINIO` y la URL del contrato).
3. Variables nuevas en el `.env` (ya agregadas): `AMQP_URL`, `AMQP_TIMEOUT_S`, `CICLO_INTERVALO_S`
   y `DOMINIO`.

Se probó con un Caddy temporal frente a la API anterior: Let's Encrypt emitió el certificado
de `13-59-144-83.sslip.io` (validez de 90 días, renovación automática) y
`https://13-59-144-83.sslip.io/health` responde 200 con el certificado verificado.

## Después del despliegue

```bash
cd ~/notificaciones
docker compose -f docker-compose.prod.yml ps              # los 4 servicios arriba
docker compose -f docker-compose.prod.yml logs --tail 20 planificador   # "Ciclo completado"
docker compose -f docker-compose.prod.yml logs --tail 20 caddy          # certificado obtenido

# Llaves de los equipos (se muestran una sola vez; entregarlas por un canal privado):
for rol in inventario fabricacion notificaciones; do
  docker compose -f docker-compose.prod.yml exec -T api python -m scripts.crear_api_key --rol $rol
done

curl https://13-59-144-83.sslip.io/health
```

Cada rol admite dos llaves activas, para rotarlas sin cortar el servicio
(`scripts.desactivar_api_key --id N`).

## Si algo falla

- **El CD dice "Falta X en .env"**: agregar la variable y relanzar el workflow.
- **`/health` responde en el servidor pero no por HTTPS**: revisar el security group (80 y 443),
  que el dominio resuelva a la IP (`getent hosts $DOMINIO`) y `logs caddy`. Let's Encrypt limita los
  intentos fallidos repetidos: conviene corregir antes de reintentar muchas veces.
- **Notificaciones que no salen a la cola**: `AMQP_URL` mal escrita o broker caído. La API sigue
  respondiendo 201 y el planificador las publica cuando el broker vuelve (3 intentos).
- **Volver atrás**: en el `.env`, poner el `API_IMAGE` de un commit anterior y
  `docker compose -f docker-compose.prod.yml up -d`.

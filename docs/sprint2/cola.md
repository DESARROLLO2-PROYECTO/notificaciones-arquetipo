# Cola de mensajes (base del Sprint 2)

Deja lista la publicación en RabbitMQ que usan HU-NOT-03 (publicar), HU-NOT-05 y el worker de
entrega de HU-NOT-17. Según el DAS: `aio-pika`, RabbitMQ en CloudAMQP, adapter reemplazable.

## Topología

- Exchange `notificaciones`, tipo **direct**, durable.
- Una cola durable por equipo que recibe, `notif.<destino>` (`notif.inventario`,
  `notif.fabricacion`), enlazada con la clave de ruteo igual al destino.
- El mensaje es persistente y trae solo `{"id": "<uuid>", "tipo": "<tipo>"}`. El worker lee el resto
  desde la base de datos (HU-NOT-03, criterio 1).
- Se publica con confirmación del broker y `mandatory`: si nadie recibe el mensaje, falla en vez
  de perderse.

## Código

| Pieza | Dónde |
|---|---|
| Puerto `Publicador`, `MensajeNotificacion`, error `ColaNoDisponible` | `app/domain/puertos.py`, `app/domain/errores.py` |
| Adapter `PublicadorAmqp`, `sondear`, `obtener_publicador` | `app/infrastructure/broker.py` |
| Configuración `AMQP_URL`, `AMQP_TIMEOUT_S` | `app/config.py`, `.env.example` |
| Sonda de conexión | `python -m scripts.verificar_cola` |

`PublicadorAmqp.publicar()` es síncrono, como el resto del servicio. Por dentro mantiene una
conexión robusta (se reabre sola) en un bucle propio. Si el broker no confirma en
`AMQP_TIMEOUT_S`, lanza `ColaNoDisponible`: HU-NOT-03 la usa para dejar la notificación en
`pendiente_publicacion` (criterio 6). Sin `AMQP_URL`, la API arranca igual y `obtener_publicador()`
lanza `ColaNoDisponible`.

HU-NOT-03 solo debe inyectar el puerto en `ServicioNotificaciones` desde `app/api/deps.py` con
`obtener_publicador()`.

## En local

`docker compose up --build` levanta también RabbitMQ (`rabbitmq:3.13.7-alpine`). Con el `.env`
copiado de `.env.example` ya queda conectado. Para ver las colas:

```bash
docker compose exec rabbitmq rabbitmqctl list_queues name messages
docker compose exec api python -m scripts.verificar_cola
```

## Con CloudAMQP (producción)

1. Crear una instancia del plan gratuito en cloudamqp.com y copiar su **AMQP URL** (`amqps://...`).
2. Comprobarla desde cualquier máquina con el proyecto instalado:

   ```bash
   AMQP_URL='amqps://usuario:clave@host/vhost' uv run python -m scripts.verificar_cola
   ```

   Debe imprimir `Broker OK: ...`. No imprime la URL ni la clave si falla.
3. Poner `AMQP_URL=amqps://...` en el `.env` de la EC2. `cd.yml` solo reemplaza `API_IMAGE`, así
   que ese valor no se pierde en los despliegues.

Solo la API y el worker tienen credenciales del broker (HU-NOT-03, criterio 3). El plan gratuito
permite pocas conexiones simultáneas: el adapter usa una sola por proceso.

## Pruebas

- `tests/unit/test_broker.py`: formato del mensaje, destinos, configuración y sonda sin broker.
- `tests/integration/test_broker.py`: RabbitMQ real con testcontainers. Entrega por destino,
  persistencia, topología repetible, broker caído y credenciales incorrectas.

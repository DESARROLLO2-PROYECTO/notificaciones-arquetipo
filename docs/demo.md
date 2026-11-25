# Demo con equipos falsos

`python -m scripts.demo` hace que **Inventario** y **Fabricación** (falsos) le pidan notificaciones
al módulo, tal como lo harían sus APIs reales, y va contando en pantalla qué pasa y por qué. Cada
escena se comprueba sola: al final muestra un resumen con ✓ o ✗.

## Preparación local (2 minutos)

```bash
cp .env.example .env
docker compose up --build                 # API, PostgreSQL y RabbitMQ
uv run python -m scripts.demo --preparar  # crea las 3 llaves y las guarda en .demo.env
uv run python -m scripts.demo             # el demo, con pausas (Enter para avanzar)
```

Para ver también los mensajes que llegan a la cola local, agregue
`AMQP_URL=amqp://notif:cambiar_clave@localhost:5672/` antes del comando. Sin `AMQP_URL` el demo
omite esa escena y sigue.

## Contra otra máquina (cambiar la IP)

La dirección se define con `--url` o con la variable `DEMO_URL`:

```bash
uv run python -m scripts.demo --url http://192.168.1.50:8090
# o
DEMO_URL=http://192.168.1.50:8090 uv run python -m scripts.demo
```

Las llaves (las entrega Notificaciones, una por rol) y la cola van por variables de entorno o en
`.demo.env` (ignorado por git), una línea `CLAVE=valor` por variable:

| Variable | Para qué |
|---|---|
| `DEMO_URL` | Dirección de la API (por defecto `http://localhost:8090`) |
| `DEMO_LLAVE_INVENTARIO` | Llave del rol `inventario` |
| `DEMO_LLAVE_FABRICACION` | Llave del rol `fabricacion` |
| `DEMO_LLAVE_ADMIN` | Llave del rol `notificaciones` (solo para el ciclo) |
| `AMQP_URL` | Broker para mirar las colas; debe ser el mismo que usa esa API (CloudAMQP: `amqps://...`) |

Prioridad: argumento, variable de entorno, `.demo.env`. `--preparar` solo sirve con el
`docker compose` local.

## Opciones

| Opción | Efecto |
|---|---|
| `--rapido` | Sin pausas entre escenas (por ejemplo, para grabar o para el CI) |
| `--sin-color` | Salida sin colores (también con `NO_COLOR=1`) |
| `--broker-caido` | Agrega la escena 7: se apaga RabbitMQ a mano y se ve que no se pierde nada |
| `--espera-reintento N` | Segundos de espera antes del reintento de esa escena (65 por defecto) |

Códigos de salida: `0` todo bien, `1` alguna comprobación falló, `2` no se pudo ejecutar (faltan
llaves o la API no responde).

## Guion sugerido

| Escena | Qué se ve | Qué decir |
|---|---|---|
| 1 | Inventario reporta stock bajo y reintenta | Se registra la notificación y se activa una alerta. El reintento no duplica: devuelve la original |
| 2 | 401, 403 y 422 | Sin llave no entra nadie; cada equipo solo emite sus tipos; los datos se validan y se indica el campo |
| 3 | Fabricación reporta una condición urgente | Otro tipo, otro destino y otro plazo de vencimiento (60 minutos) |
| 4 | Los mensajes llegan a la cola | Cada notificación se publica en la cola de su destino, con su id y su tipo |
| 5 | Inventario repone el artículo | Se cierra la alerta; si vuelve a bajar, se notifica de nuevo |
| 6 | El ciclo | Solo la administración lo ejecuta; cierra alertas vencidas y reintenta publicaciones |
| 7 *(opcional)* | Se apaga RabbitMQ | La API sigue respondiendo 201; al volver el broker, el ciclo publica lo pendiente |

La escena 7 pide dos acciones a mano: `docker compose stop rabbitmq` y luego
`docker compose start rabbitmq`. El ciclo solo reintenta notificaciones de más de un minuto, por
eso espera 65 s (con una cuenta regresiva).

## Cómo funciona por dentro

- Los equipos falsos usan sus propias llaves y hacen las mismas peticiones HTTP que haría un
  equipo real (`scripts/demo/equipos_falsos.py`).
- Para la cola crea una cola temporal y exclusiva enlazada al mismo exchange: recibe una **copia**
  de cada mensaje, no se lo quita al worker de entrega y se borra al terminar (`scripts/demo/cola.py`).
- Cada corrida usa códigos nuevos (`DEMO-ACERO-<hora>-<azar>`), así que se puede repetir sin
  chocar con alertas anteriores. Las alertas del demo vencen solas (24 h o 60 min).
- `tests/integration/test_demo.py` ejecuta el demo completo, con la escena 7, contra Postgres y
  RabbitMQ reales: si la API cambia y el guion deja de cumplirse, el CI lo avisa.

Cuando exista la entrega por webhook (HU-NOT-17), se agrega una escena con un receptor falso que
verifica la firma `X-Signature`.

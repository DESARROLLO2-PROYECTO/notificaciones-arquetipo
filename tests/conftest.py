"""Las pruebas no deben conectarse al broker del .env de quien las corre."""

import os

os.environ["AMQP_URL"] = ""

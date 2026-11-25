import logging


class OcultarQuery(logging.Filter):
    """El log de acceso de uvicorn imprime la URL completa: si un cliente manda su llave en la
    URL (error que la API ignora con 401), no debe quedar escrita en el log."""

    def filter(self, record: logging.LogRecord) -> bool:
        argumentos = record.args
        if isinstance(argumentos, tuple) and len(argumentos) >= 3:
            ruta = argumentos[2]
            if isinstance(ruta, str) and "?" in ruta:
                record.args = (
                    *argumentos[:2],
                    ruta.split("?", 1)[0] + "?<omitido>",
                    *argumentos[3:],
                )
        return True

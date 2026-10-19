from __future__ import annotations

import os

from waitress import serve

from wsgi import app


if __name__ == "__main__":
    serve(
        app,
        host=os.getenv("APP_HOST", "0.0.0.0"),
        port=int(os.getenv("APP_PORT", "8080")),
        threads=int(os.getenv("APP_THREADS", "6")),
        channel_timeout=120,
    )

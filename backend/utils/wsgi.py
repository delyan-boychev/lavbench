"""Gunicorn entrypoint: apply gevent monkey patches before importing the app.

Without this, the gevent worker class never patches the stdlib, so blocking calls
(time.sleep, socket I/O) inside greenlets stall all other greenlets on the worker.
psycogreen does the same for psycopg2, whose C library otherwise blocks the whole
worker on every query.
"""

import gevent.monkey  # type: ignore[import-untyped]

gevent.monkey.patch_all()

import psycogreen.gevent  # noqa: E402

psycogreen.gevent.patch_psycopg()

from config import Config  # noqa: E402

# Only the web process gets the idle-in-transaction timeout (see Config)
Config.use_web_process_engine_options()

from app import app as app  # noqa: E402  (gunicorn target `utils.wsgi:app`)

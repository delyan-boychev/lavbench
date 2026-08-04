"""Gunicorn entrypoint: apply gevent monkey patches before importing the app.

Without this, the gevent worker class never patches the stdlib, so blocking calls
(time.sleep, socket I/O) inside greenlets stall all other greenlets on the worker.
"""

import gevent.monkey  # type: ignore[import-untyped]

gevent.monkey.patch_all()

from app import app as app  # noqa: E402  (gunicorn target `wsgi:app`)

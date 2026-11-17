"""Release SQLite transactions after every Django request."""

import logging
import sqlite3

from django.conf import settings

from .db import request_connections
from .http import json_response


logger = logging.getLogger(__name__)


class PortalMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = request_connections.set([])
        try:
            response = self.get_response(request)
            if request.path.startswith("/api/"):
                response["Cache-Control"] = "no-store"
            return response
        finally:
            for connection in request_connections.get():
                connection.close()
            request_connections.reset(token)

    def process_exception(self, request, error):
        if settings.DATABASES["default"]["ENGINE"] == "django.db.backends.sqlite3":
            if not isinstance(error, sqlite3.OperationalError):
                return None
            error_code = getattr(error, "sqlite_errorcode", 0) & 255
            if error_code in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                return json_response(
                    {"error": "The server is busy saving submissions. Please try again."},
                    status=503,
                    headers={"Retry-After": "1"},
                )
        else:
            import psycopg

            if not isinstance(error, psycopg.OperationalError):
                return None

        logger.error("Database operation failed", exc_info=True)
        return json_response({"error": "A database error occurred. Please contact your teacher."}, status=500)

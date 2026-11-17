"""PostgreSQL-only settings for the classroom portal."""

import os
from django.core.exceptions import ImproperlyConfigured
from .base_settings import *

DATABASE_ENGINE = os.environ.get("EXAM_PORTAL_DB_ENGINE", "postgresql").lower()
if DATABASE_ENGINE != "postgresql":
    raise ImproperlyConfigured("AralHub requires PostgreSQL. SQLite is disabled.")
if os.environ.get("EXAM_PORTAL_DB_PATH"):
    raise ImproperlyConfigured(
        "EXAM_PORTAL_DB_PATH is no longer supported. Use the PostgreSQL launcher."
    )
postgres_required = ("EXAM_PORTAL_DB_NAME", "EXAM_PORTAL_DB_USER", "EXAM_PORTAL_DB_PASSWORD")
missing_postgres_settings = [name for name in postgres_required if not os.environ.get(name)]
if missing_postgres_settings:
    raise ImproperlyConfigured(
        "PostgreSQL configuration is required. Start with start_aralhub.bat or the "
        "'AralHub LAN' scheduled task. Missing environment variables: "
        + ", ".join(missing_postgres_settings)
    )
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ["EXAM_PORTAL_DB_NAME"],
        "USER": os.environ["EXAM_PORTAL_DB_USER"],
        "PASSWORD": os.environ["EXAM_PORTAL_DB_PASSWORD"],
        "HOST": os.environ.get("EXAM_PORTAL_DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("EXAM_PORTAL_DB_PORT", "5432"),
        "OPTIONS": {"connect_timeout": int(os.environ.get("EXAM_PORTAL_DB_CONNECT_TIMEOUT", "10"))},
    }
}

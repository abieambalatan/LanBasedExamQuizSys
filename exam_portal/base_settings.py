"""Settings shared by the local development and Waitress LAN servers."""

import os
from pathlib import Path
import secrets
import socket


BASE_DIR = Path(__file__).resolve().parent.parent


def _secret_key():
    configured = os.environ.get("EXAM_PORTAL_SECRET_KEY")
    if configured:
        return configured
    path = BASE_DIR / ".django_secret_key"
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(secrets.token_urlsafe(64))
    except FileExistsError:
        pass
    return path.read_text(encoding="utf-8").strip()


def _local_hosts():
    hosts = {"localhost", "127.0.0.1", "[::1]", socket.gethostname().lower()}
    try:
        hosts.update(address[4][0] for address in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    return sorted(hosts)


SECRET_KEY = _secret_key()
DEBUG = os.environ.get("EXAM_PORTAL_DEBUG", "0") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("EXAM_PORTAL_ALLOWED_HOSTS", "").split(",") if host.strip()] or _local_hosts()
ROOT_URLCONF = "exam_portal.urls"
WSGI_APPLICATION = "exam_portal.wsgi.application"
ASGI_APPLICATION = "exam_portal.asgi.application"
INSTALLED_APPS = [
    "portal.apps.PortalAdminConfig",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "portal.apps.PortalConfig",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "portal" / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
STATIC_URL = "/static/"
LOGIN_URL = "/login"
LOGOUT_REDIRECT_URL = "/login"
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "portal.middleware.PortalMiddleware",
    "django.middleware.common.CommonMiddleware",
    "portal.sessions.PortalSessionMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
# Signed sessions avoid a database write on every student's request.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_NAME = "aralhub_session"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_FAILURE_VIEW = "portal.http.csrf_failure"
CSRF_TRUSTED_ORIGINS = [origin.strip() for origin in os.environ.get("EXAM_PORTAL_CSRF_TRUSTED_ORIGINS", "").split(",") if origin.strip()]
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = os.environ.get("EXAM_PORTAL_HTTPS", "0") == "1"
X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
APPEND_SLASH = False
USE_TZ = True
TIME_ZONE = "Asia/Singapore"
LANGUAGE_CODE = "en-us"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
# Private documents are served only through authenticated learning endpoints.
MEDIA_ROOT = Path(os.environ.get("EXAM_PORTAL_UPLOAD_ROOT", BASE_DIR / "uploads"))
LEARNING_FILE_MAX_BYTES = 25 * 1024 * 1024
FILE_UPLOAD_HANDLERS = [
    "portal.learning_uploads.LimitedUploadHandler",
    "django.core.files.uploadhandler.MemoryFileUploadHandler",
    "django.core.files.uploadhandler.TemporaryFileUploadHandler",
]

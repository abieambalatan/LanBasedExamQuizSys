"""Isolated legacy test fixtures; never selected by the portal launcher.

File fixtures must live in the OS temporary directory, outside this workspace.
"""

import os
from pathlib import Path
import tempfile
from django.core.exceptions import ImproperlyConfigured
from .base_settings import *

PORTAL_SQLITE_TESTS = True
_test_path = os.environ.get("EXAM_PORTAL_DB_PATH", ":memory:")
if _test_path != ":memory:":
    _resolved = Path(_test_path).resolve()
    if not _resolved.is_relative_to(Path(tempfile.gettempdir()).resolve()) or _resolved.is_relative_to(BASE_DIR):
        raise ImproperlyConfigured("Test database files must stay outside the workspace in the OS temporary directory.")
DATABASES = {"default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": _test_path,
    "OPTIONS": {"timeout": 30},
}}

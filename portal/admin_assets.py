"""Serve Django's bundled admin assets through the existing LAN WSGI server."""

from pathlib import Path
import mimetypes
from django.contrib.staticfiles import finders
from django.http import FileResponse, Http404


def admin_asset(request, path):
    if not path.startswith("admin/") or any(part.startswith(".") for part in Path(path).parts):
        raise Http404
    filename = finders.find(path)
    if not filename:
        raise Http404
    return FileResponse(open(filename, "rb"), content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")

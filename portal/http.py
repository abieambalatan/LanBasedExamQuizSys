"""JSON API responses and dispatch using Django's request/response objects."""

from functools import wraps
import json

from django.core.exceptions import BadRequest
from django.http import JsonResponse


def json_response(data, status=200, headers=None):
    return JsonResponse(data, safe=isinstance(data, dict), status=status, headers=headers)


def read_json(request):
    try:
        data = json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError) as error:
        raise BadRequest("Request body must contain valid JSON.") from error
    if not isinstance(data, dict):
        raise BadRequest("Request body must be a JSON object.")
    return data


def endpoint(**handlers):
    """Dispatch each URL's HTTP methods without changing the frontend API."""
    @wraps(next(iter(handlers.values())))
    def view(request, **kwargs):
        method = "GET" if request.method == "HEAD" else request.method
        handler = handlers.get(method)
        if handler is None:
            return json_response({"error": "Method not allowed."}, status=405, headers={"Allow": ", ".join(handlers)})
        try:
            return handler(request, **kwargs)
        except BadRequest as error:
            return json_response({"error": str(error)}, status=400)
    return view


def csrf_failure(request, reason=""):
    return json_response({"error": "Your security token has expired. Refresh the page and try again.", "code": "csrf_failed"}, status=403)


def not_found(request, exception=None):
    return json_response({"error": "Not found."}, status=404)


def server_error(request):
    return json_response({"error": "A server error occurred. Please contact your teacher."}, status=500)

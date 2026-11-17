"""Select signed workspace cookies and replace identities at shared sign-in."""

from django.conf import settings
from django.contrib.sessions.middleware import SessionMiddleware


class PortalSessionMiddleware(SessionMiddleware):
    def process_request(self, request):
        role = request.headers.get("X-Portal-Role", "") if request.path.startswith("/api/") else ""
        if request.path in ("/student", "/", "/index.html"):
            role = "student"
        elif request.path == "/teacher":
            role = "teacher"
        # Normal document links cannot set headers. Select the same independent
        # signed cookie used by the originating workspace for these GETs only.
        if not role and request.method in ("GET", "HEAD") and request.path.startswith("/api/learning/files/"):
            role = request.GET.get("portalRole", "")
        default = settings.SESSION_COOKIE_NAME
        cookie = f"{default}_{role}" if role in ("student", "teacher") else default
        request.portal_session_cookie = cookie
        request.session = self.SessionStore(request.COOKIES.get(cookie))
        # Upgrade an existing matching login without asking for its password again.
        # An admin cookie must never be interpreted as a teacher/student login.
        if cookie != default and default in request.COOKIES:
            legacy = self.SessionStore(request.COOKIES[default])
            account = legacy.get("account")
            if isinstance(account, dict) and account.get("role") == role and not legacy.get("_auth_user_id"):
                request.portal_legacy_cookie_migrated = True
                if cookie not in request.COOKIES:
                    request.session = legacy
                    request.session.modified = True

    def process_response(self, request, response):
        default = settings.SESSION_COOKIE_NAME
        cookie = getattr(request, "portal_session_cookie", default)
        original_cookies = request.COOKIES
        if cookie != default:
            # Let Django retain its standard signing, expiry, and logout behavior.
            # Alias only this request's cookie dictionary; settings stay untouched.
            request.COOKIES = dict(original_cookies)
            request.COOKIES.pop(default, None)
            if cookie in original_cookies:
                request.COOKIES[default] = original_cookies[cookie]
        try:
            response = super().process_response(request, response)
        finally:
            request.COOKIES = original_cookies
        if cookie != default and default in response.cookies:
            morsel = response.cookies.pop(default)
            response.cookies[cookie] = morsel.value
            for attribute, value in morsel.items():
                response.cookies[cookie][attribute] = value
        if cookie != default and getattr(request, "portal_legacy_cookie_migrated", False):
            response.delete_cookie(default, path=settings.SESSION_COOKIE_PATH, domain=settings.SESSION_COOKIE_DOMAIN, samesite=settings.SESSION_COOKIE_SAMESITE)
        if getattr(request, "portal_replace_other_sessions", False):
            # Shared sign-in replaces the browser's previous identity. Apply
            # deletions after renaming Django's cookie so an old superadmin or
            # teacher login cannot remain usable after signing in as a student.
            for other in (default, f"{default}_teacher", f"{default}_student"):
                if other != cookie:
                    response.delete_cookie(other, path=settings.SESSION_COOKIE_PATH, domain=settings.SESSION_COOKIE_DOMAIN, samesite=settings.SESSION_COOKIE_SAMESITE)
        return response

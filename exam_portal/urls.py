from django.urls import include, path
from django.contrib import admin
from django.views.generic import RedirectView
from portal.admin_assets import admin_asset


urlpatterns = [
    path("admin/", admin.site.urls),
    path("admin", RedirectView.as_view(url="/admin/", permanent=False)),
    path("admin.html", RedirectView.as_view(url="/admin/", permanent=False)),
    path("static/<path:path>", admin_asset),
    path("", include("portal.urls")),
]
handler404 = "portal.http.not_found"
handler500 = "portal.http.server_error"

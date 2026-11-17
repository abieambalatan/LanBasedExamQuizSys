from django.contrib.admin import AdminSite
from django.conf import settings
from django.contrib.auth.views import LogoutView
from django.http import HttpResponseRedirect, JsonResponse
from django.urls import path
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache


class ExamHubAdminSite(AdminSite):
    site_header = "AbieksExamSys"
    site_title = "AbieksExamSys"
    index_title = "Manage your school"
    site_url = "/"
    index_template = "admin/portal/dashboard.html"

    def dashboard_payload(self):
        from .models import Student, Teacher, Exam
        return {
            "students": Student.objects.filter(deleted_at__isnull=True).count(),
            "teachers": Teacher.objects.filter(deleted_at__isnull=True).count(),
            "assessments": Exam.objects.count(),
        }

    def index(self, request, extra_context=None):
        if not self.has_permission(request):
            return super().index(request, extra_context=extra_context)
        return super().index(request, extra_context={**(extra_context or {}), "campus": self.dashboard_payload()})

    def get_urls(self):
        return [path("live/", self.admin_view(self.live_dashboard), name="campus-live")] + super().get_urls()

    def live_dashboard(self, request):
        return JsonResponse(self.dashboard_payload())

    def has_permission(self, request):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    @method_decorator(never_cache)
    def login(self, request, extra_context=None):
        return HttpResponseRedirect(settings.LOGIN_URL)

    def logout(self, request, extra_context=None):
        return LogoutView.as_view(next_page=settings.LOGOUT_REDIRECT_URL, redirect_field_name=None)(request)

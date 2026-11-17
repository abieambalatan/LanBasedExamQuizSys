from django.apps import AppConfig
from django.contrib.admin.apps import AdminConfig


class PortalAdminConfig(AdminConfig):
    default_site = "portal.admin_site.ExamHubAdminSite"


class PortalConfig(AppConfig):
    name = "portal"
    verbose_name = "AbieksExamSys assessments"

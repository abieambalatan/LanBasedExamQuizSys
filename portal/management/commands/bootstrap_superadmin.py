"""Provision the original administrator as a Django superuser once."""

import os
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = "Create the initial Django superuser using existing configured administrator credentials; never reset an existing account."

    def handle(self, *args, **options):
        from portal.views import _load_admin_password
        username = os.environ.get("EXAM_PORTAL_ADMIN_USERNAME", "administrator")
        password = _load_admin_password()
        User = get_user_model()
        with transaction.atomic():
            user = User.objects.filter(username=username).first()
            if user:
                if not (user.is_superuser and user.is_staff and user.is_active):
                    raise CommandError("The configured username already belongs to a non-superadmin account. Choose a different administrator username.")
                self.stdout.write("Existing Django superadmin retained; password unchanged.")
                return
            if not password:
                raise CommandError("Set EXAM_PORTAL_ADMIN_PASSWORD or run manage.py createsuperuser to create a Django superadmin.")
            User.objects.create_superuser(username=username, password=password)
        self.stdout.write("Created the initial Django superadmin using the existing configured credentials.")

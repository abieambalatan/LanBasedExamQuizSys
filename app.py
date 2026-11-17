"""Start the Django assessment portal with Waitress on the classroom LAN."""

import os


def server_options():
    return {
        "host": os.environ.get("EXAM_PORTAL_HOST", "0.0.0.0"),
        "port": int(os.environ.get("EXAM_PORTAL_PORT", "5000")),
        "threads": int(os.environ.get("EXAM_PORTAL_THREADS", "16")),
        # Stay below Windows select()'s socket limit, with room for 200 clients.
        "connection_limit": 400,
        "backlog": 1024,
        "channel_timeout": 30,
        "cleanup_interval": 5,
    }


def main():
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "exam_portal.settings")
    import django
    from django.conf import settings
    from django.core.management import call_command
    from waitress import serve

    django.setup()
    if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
        raise SystemExit("The classroom server requires PostgreSQL. Test databases cannot serve the portal.")
    call_command("migrate", interactive=False, verbosity=0)
    call_command("bootstrap_superadmin", verbosity=0)
    from exam_portal.wsgi import application

    options = server_options()
    print(f"AbieksExamSys Django: http://{options['host']}:{options['port']} (Waitress, {options['threads']} workers)", flush=True)
    serve(application, **options)


if __name__ == "__main__":
    main()

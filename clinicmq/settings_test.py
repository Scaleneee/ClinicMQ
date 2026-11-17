"""Settings for running tests without touching Supabase.

    python manage.py test --settings=clinicmq.settings_test

Same project settings, but an in-memory SQLite database, a fast password
hasher and emails kept in memory.
"""

from .settings import *  # noqa: F401,F403

DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"

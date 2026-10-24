import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent

DEFAULT_SECRET_KEY = "dev-only-change-me"

SECRET_KEY = os.environ.get("SECRET_KEY", DEFAULT_SECRET_KEY)
DEBUG = os.environ.get("DEBUG", "True").lower() in ("1", "true", "yes", "on")
_allowed = os.environ.get("ALLOWED_HOSTS", "*")
ALLOWED_HOSTS = [h.strip() for h in _allowed.split(",") if h.strip()] or ["*"]


def _validate_secret_key(secret_key, debug):
    """Refuse to boot in production with the shipped placeholder key."""
    if not debug and secret_key == DEFAULT_SECRET_KEY:
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a unique, unpredictable value when DEBUG=False."
        )


def _security_settings(debug):
    """HTTPS/cookie hardening switches, enabled only when DEBUG=False.

    Kept as a pure function so the production branch can be unit-tested
    without mutating the process environment.
    """
    return {
        "SECURE_SSL_REDIRECT": not debug,
        "SECURE_HSTS_SECONDS": 0 if debug else 31536000,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": not debug,
        "SECURE_HSTS_PRELOAD": not debug,
        "SESSION_COOKIE_SECURE": not debug,
        "CSRF_COOKIE_SECURE": not debug,
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https") if not debug else None,
    }


_validate_secret_key(SECRET_KEY, DEBUG)
globals().update(_security_settings(DEBUG))

# Clickjacking protection is safe to enable in every environment.
X_FRAME_OPTIONS = "DENY"

# Password strength requirements enforced by Django auth / password reset.
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "reviews",
]
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]
ROOT_URLCONF = "config.urls"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "django.template.context_processors.i18n",
    ]},
}]

# Database: DATABASE_URL for Postgres, fallback to SQLite for local dev / tests
_db_url = os.environ.get("DATABASE_URL", "")
if _db_url:
    # simple parse: postgres://user:pass@host:port/dbname  -> use psycopg
    # we rely on dj-database-url style but keep stdlib only
    from urllib.parse import urlparse
    u = urlparse(_db_url)
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username or "",
        "PASSWORD": u.password or "",
        "HOST": u.hostname or "",
        "PORT": str(u.port or ""),
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

STATIC_URL = "static/"
USE_I18N = True
LANGUAGE_CODE = "ru"
LANGUAGES = [
    ("ru", "Русский"),
    ("ky", "Кыргызча"),
    ("en", "English"),
]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Bishkek"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

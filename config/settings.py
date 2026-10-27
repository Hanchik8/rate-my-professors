"""Django settings for ProfLens.

Все настройки берутся из переменных окружения (см. .env.example).
Правило простое: DEBUG=True — удобная разработка, DEBUG=False — боевой режим
со всеми защитами. В боевом режиме без нормального SECRET_KEY и ALLOWED_HOSTS
приложение специально не запустится.
"""
import os
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Minimal .env reader: KEY=VALUE lines, real environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(BASE_DIR / ".env")


def env(name, default=""):
    return os.environ.get(name, default)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_int(name, default=0):
    value = os.environ.get(name)
    return int(value) if value not in (None, "") else default


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# True while `manage.py test` is running (used only for static files storage below).
TESTING = len(sys.argv) > 1 and sys.argv[1] == "test"

DEBUG = env_bool("DEBUG", False)

# --- Secret key -------------------------------------------------------------
_INSECURE_KEYS = {"", "dev-only-change-me", "change-me-in-production", "change-me", "secret"}
SECRET_KEY = env("SECRET_KEY")
if DEBUG and not SECRET_KEY:
    SECRET_KEY = "dev-only-change-me"
if not DEBUG and (
    SECRET_KEY in _INSECURE_KEYS
    or SECRET_KEY.startswith("django-insecure")
    or len(SECRET_KEY) < 50
    or len(set(SECRET_KEY)) < 5
):
    raise ImproperlyConfigured(
        "DEBUG=False требует надёжный SECRET_KEY (50+ случайных символов). "
        "Сгенерируйте: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
    )

# --- Hosts ------------------------------------------------------------------
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]" if DEBUG else "")
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DEBUG=False требует ALLOWED_HOSTS, например: ALLOWED_HOSTS=proflens.kg,www.proflens.kg")
# Full origins with scheme, e.g. https://proflens.kg (needed for CSRF behind HTTPS proxies)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

# --- Apps -------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "reviews",
]
MIDDLEWARE = [
    # Answers /healthz before host checks and HTTPS redirects (for Docker/load balancers)
    "reviews.middleware.HealthCheckMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",  # needed for ru/ky/en, keep it here
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
        "django.template.context_processors.i18n",
        "reviews.context_processors.site",
    ]},
}]

# --- Database ---------------------------------------------------------------
# DATABASE_URL=postgres://user:pass@host:5432/dbname?sslmode=require  -> PostgreSQL
# empty -> SQLite file (only for local development)
_db_url = env("DATABASE_URL")
if _db_url:
    _u = urlparse(_db_url)
    if _u.scheme not in ("postgres", "postgresql"):
        raise ImproperlyConfigured("DATABASE_URL должен начинаться с postgres://")
    DATABASES = {"default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": _u.path.lstrip("/"),
        "USER": _u.username or "",
        "PASSWORD": _u.password or "",
        "HOST": _u.hostname or "",
        "PORT": str(_u.port or ""),
        "OPTIONS": dict(parse_qsl(_u.query)),
        # keep connections open between requests, check them before reuse
        "CONN_MAX_AGE": env_int("DB_CONN_MAX_AGE", 60),
        "CONN_HEALTH_CHECKS": True,
    }}
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

# --- Cache ------------------------------------------------------------------
# REDIS_URL=redis://redis:6379/0 shares cache and rate limits between all workers.
# Without it every process has its own in-memory cache (fine for one server).
_redis_url = env("REDIS_URL")
if _redis_url:
    CACHES = {"default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": _redis_url,
        "KEY_PREFIX": "proflens",
        "TIMEOUT": 300,
    }}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "proflens"}}
# Seconds to cache search results / statistics. 0 disables.
READ_CACHE_SECONDS = env_int("READ_CACHE_SECONDS", 60)

SESSION_ENGINE = "django.contrib.sessions.backends.cached_db"

# --- Static files -----------------------------------------------------------
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {
        "BACKEND": (
            "django.contrib.staticfiles.storage.StaticFilesStorage"
            if DEBUG or TESTING
            # gzip/brotli + file names with hashes, so browsers can cache forever
            else "whitenoise.storage.CompressedManifestStaticFilesStorage"
        ),
    },
}

# --- Auth -------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 8}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

# --- Email ------------------------------------------------------------------
# Without EMAIL_HOST letters are printed to the console/log.
EMAIL_HOST = env("EMAIL_HOST")
EMAIL_BACKEND = (
    "django.core.mail.backends.smtp.EmailBackend" if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend"
)
EMAIL_PORT = env_int("EMAIL_PORT", 587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD")
EMAIL_USE_TLS = env_bool("EMAIL_USE_TLS", True)
EMAIL_TIMEOUT = 10
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", "ProfLens <noreply@localhost>")
# True: only users who confirmed their email can post reviews, vote and add professors.
REQUIRE_EMAIL_VERIFICATION = env_bool("REQUIRE_EMAIL_VERIFICATION", False)

# --- Security ---------------------------------------------------------------
# How many reverse proxies (Caddy, nginx, a hosting load balancer) sit in front
# of gunicorn. 0 = nobody, use the TCP address. Must match reality, otherwise
# clients can fake their IP via X-Forwarded-For.
TRUSTED_PROXY_COUNT = env_int("TRUSTED_PROXY_COUNT", 0)
if TRUSTED_PROXY_COUNT > 0:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

SECURE_SSL_REDIRECT = env_bool("SECURE_SSL_REDIRECT", not DEBUG)
SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", not DEBUG)
CSRF_COOKIE_SECURE = env_bool("CSRF_COOKIE_SECURE", not DEBUG)
LANGUAGE_COOKIE_SECURE = SESSION_COOKIE_SECURE
LANGUAGE_COOKIE_SAMESITE = "Lax"
SECURE_HSTS_SECONDS = env_int("SECURE_HSTS_SECONDS", 0 if DEBUG else 60 * 60 * 24 * 365)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", True)
SECURE_HSTS_PRELOAD = env_bool("SECURE_HSTS_PRELOAD", False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_AGE = 60 * 60 * 24 * 14
DATA_UPLOAD_MAX_MEMORY_SIZE = 1024 * 1024  # 1 MB is plenty for our forms
# Admin lives on a less obvious path in production, e.g. ADMIN_URL=manage-7f3k/
ADMIN_URL = env("ADMIN_URL", "admin/")

# Rate limits for POST requests: "count/period", period is s, m, h or d.
# GET requests are never limited. Over the limit the user gets HTTP 429.
RATELIMIT_ENABLED = env_bool("RATELIMIT_ENABLED", True)
RATELIMITS = {
    "login": env("RATELIMIT_LOGIN", "10/m"),
    "signup": env("RATELIMIT_SIGNUP", "5/h"),
    "review": env("RATELIMIT_REVIEW", "10/h"),
    "vote": env("RATELIMIT_VOTE", "60/m"),
    "report": env("RATELIMIT_REPORT", "20/h"),
    "add_professor": env("RATELIMIT_ADD_PROFESSOR", "10/h"),
    "resend_verification": env("RATELIMIT_RESEND", "3/h"),
}

# --- i18n -------------------------------------------------------------------
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

# Site name / public URL used in meta tags and emails
SITE_NAME = "ProfLens"
SITE_URL = env("SITE_URL", "").rstrip("/")

# --- Logging: everything to stdout, Docker collects it ----------------------
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"plain": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "plain"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", "INFO")},
    "loggers": {
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "django.security": {"handlers": ["console"], "level": "WARNING", "propagate": False},
    },
}

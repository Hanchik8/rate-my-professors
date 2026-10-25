import os
import sys
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path):
    """Minimal stdlib .env loader so local dev works without extra deps.

    Existing environment variables always win so real deployments can override
    the file. Missing files are ignored.
    """
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")

# Django's test command runs with DEBUG off by default; force a safe dev mode so
# `manage.py test` never requires production secrets or strict HTTPS flags.
_is_test = sys.argv[1:2] == ["test"]

DEFAULT_SECRET_KEY = "dev-only-change-me"
# Used only while running the test suite; never valid for production boot.
TEST_SECRET_KEY = "test-secret-key-for-ci-only-must-not-be-used-in-production-0123456789"
# Safe fallback that works for local development without exposing the app to
# Host-header attacks the way a bare "*" would.
DEFAULT_ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]
TEST_ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]


def _parse_bool(value, default=False):
    """Parse common truthy/falsy strings; fall back to `default` when unset."""
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def _get_debug(is_test, raw):
    """DEBUG comes from the environment, defaulting to False (prod-safe)."""
    if is_test:
        return True
    return _parse_bool(raw, default=False)


def _get_allowed_hosts(raw, is_test=False):
    """Parse ALLOWED_HOSTS, falling back to safe localhost-only defaults."""
    hosts = [h.strip() for h in (raw or "").split(",") if h.strip()]
    if hosts:
        return hosts
    return list(TEST_ALLOWED_HOSTS if is_test else DEFAULT_ALLOWED_HOSTS)


DEBUG = _get_debug(_is_test, os.environ.get("DEBUG"))
if _is_test:
    SECRET_KEY = os.environ.get("SECRET_KEY") or TEST_SECRET_KEY
else:
    SECRET_KEY = os.environ.get("SECRET_KEY") or DEFAULT_SECRET_KEY
ALLOWED_HOSTS = _get_allowed_hosts(os.environ.get("ALLOWED_HOSTS"), _is_test)


def _validate_secret_key(secret_key, debug):
    """Refuse to boot in production with the shipped placeholder key."""
    if not debug and secret_key == DEFAULT_SECRET_KEY:
        raise ImproperlyConfigured(
            "SECRET_KEY must be set to a unique, unpredictable value when DEBUG=False."
        )


def _validate_allowed_hosts(hosts, debug):
    """Wildcard hosts are a dev convenience only; reject them in production."""
    if not debug and "*" in hosts:
        raise ImproperlyConfigured("ALLOWED_HOSTS must not contain '*' when DEBUG=False.")


def _get_secure_cookie(raw, default):
    """Resolve a secure-cookie flag from the environment.

    An unset variable falls back to ``default`` (``not DEBUG``), so secure
    cookies stay on in production while remaining explicitly overridable by
    ``SESSION_COOKIE_SECURE`` / ``CSRF_COOKIE_SECURE``.
    """
    if raw is None:
        return default
    return _parse_bool(raw, default=default)


def _security_settings(debug, session_secure=None, csrf_secure=None):
    """HTTPS/cookie hardening switches, enabled only when DEBUG=False.

    ``session_secure``/``csrf_secure`` let the environment override the
    debug-derived default; when left as ``None`` the secure value tracks
    ``not debug``.  Kept as a pure function so the production branch can be
    unit-tested without mutating the process environment.
    """
    return {
        "SECURE_SSL_REDIRECT": not debug,
        "SECURE_HSTS_SECONDS": 0 if debug else 31536000,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": not debug,
        "SECURE_HSTS_PRELOAD": not debug,
        "SESSION_COOKIE_SECURE": not debug if session_secure is None else session_secure,
        "CSRF_COOKIE_SECURE": not debug if csrf_secure is None else csrf_secure,
        "SECURE_CONTENT_TYPE_NOSNIFF": True,
        "SECURE_PROXY_SSL_HEADER": ("HTTP_X_FORWARDED_PROTO", "https") if not debug else None,
    }


_validate_secret_key(SECRET_KEY, DEBUG)
_validate_allowed_hosts(ALLOWED_HOSTS, DEBUG)
globals().update(
    _security_settings(
        DEBUG,
        session_secure=_get_secure_cookie(os.environ.get("SESSION_COOKIE_SECURE"), not DEBUG),
        csrf_secure=_get_secure_cookie(os.environ.get("CSRF_COOKIE_SECURE"), not DEBUG),
    )
)

# Clickjacking protection is safe to enable in every environment.
X_FRAME_OPTIONS = "DENY"

# Referrer-Policy limits how much of our URLs leak to third parties; "same-origin"
# is a safe, privacy-preserving default that can be tightened per deployment.
SECURE_REFERRER_POLICY = os.environ.get("SECURE_REFERRER_POLICY", "same-origin")

# Cookies must never be readable from JavaScript and stay same-site by default.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

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
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
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

# Rate limiting: simple fixed-window counters kept in the Django cache.
# Disabled by default while running the test suite so unrelated tests cannot
# exhaust a shared per-user/per-IP budget; the throttle tests re-enable it.
RATELIMIT_ENABLE = _parse_bool(os.environ.get("RATELIMIT_ENABLE"), default=not _is_test)
# action -> (max hits, window in seconds)
RATELIMIT = {
    "login": (10, 60),
    "review": (10, 600),
    "vote": (60, 60),
}

# Shared cache used by the rate limiter (and available for future use). A real
# multi-process deployment should point CACHE_BACKEND at Redis/Memcached so the
# limit is enforced globally instead of per worker.
CACHES = {
    "default": {
        "BACKEND": os.environ.get(
            "CACHE_BACKEND", "django.core.cache.backends.locmem.LocMemCache"
        ),
        "LOCATION": os.environ.get("CACHE_LOCATION", "proflens"),
    }
}

import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# --- Fail-safe core ---
_is_test = sys.argv[1:2] == ["test"]
if _is_test:
    DEBUG = True
else:
    DEBUG = os.environ.get("DEBUG", "False").lower() in ("1", "true", "yes", "on")

_raw_secret = os.environ.get("SECRET_KEY", "")
if not _raw_secret and _is_test:
    _raw_secret = "test-secret-key-for-ci-must-be-long-enough-50-chars-1234567890"  # nosec B105
SECRET_KEY = _raw_secret or "dev-only-change-me-please-set-SECRET_KEY-env-1234567890"  # nosec B105

_raw_hosts = os.environ.get("ALLOWED_HOSTS", "")
if not _raw_hosts and _is_test:
    _raw_hosts = "testserver,localhost,127.0.0.1"
ALLOWED_HOSTS = [h.strip() for h in _raw_hosts.split(",") if h.strip()]

REPO_BACKEND = os.environ.get("REPO_BACKEND", "").strip().lower()
_db_url = os.environ.get("DATABASE_URL", "")

TRUSTED_PROXY_COUNT = int(os.environ.get("TRUSTED_PROXY_COUNT", "0") or 0)

ADMIN_URL = os.environ.get("ADMIN_URL", "admin/").strip("/")
if not ADMIN_URL.endswith("/"):
    ADMIN_URL = ADMIN_URL + "/"

# Strict fail-safe: when not testing and DEBUG=False, require env vars
if not DEBUG and not _is_test:
    from django.core.exceptions import ImproperlyConfigured
    _sk = os.environ.get("SECRET_KEY", "")
    _ah = os.environ.get("ALLOWED_HOSTS", "")
    if not _sk or len(_sk) < 50:
        raise ImproperlyConfigured("SECRET_KEY must be set and >=50 chars when DEBUG=False")
    if len(set(_sk)) < 5:
        raise ImproperlyConfigured("SECRET_KEY must contain at least 5 distinct characters when DEBUG=False")
    if not _ah or "*" in [h.strip() for h in _ah.split(",")]:
        raise ImproperlyConfigured("ALLOWED_HOSTS must be set and not contain '*' when DEBUG=False")
    if REPO_BACKEND == "memory":
        raise ImproperlyConfigured("REPO_BACKEND=memory is not allowed when DEBUG=False")
    if not _db_url:
        raise ImproperlyConfigured("DATABASE_URL must be set (SQLite is not allowed) when DEBUG=False")
    if ADMIN_URL == "admin/":
        raise ImproperlyConfigured("ADMIN_URL must be changed from default 'admin/' when DEBUG=False")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "axes",
    "django_otp",
    "django_otp.plugins.otp_totp",
    "django_otp.plugins.otp_static",
    "reviews",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django_otp.middleware.OTPMiddleware",
    "axes.middleware.AxesMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.csp.ContentSecurityPolicyMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesBackend",
    "django.contrib.auth.backends.ModelBackend",
]

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 1
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_CLIENT_IP_CALLABLE = "reviews.net.client_ip"

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 10}},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
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

if _db_url:
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

_redis_url = os.environ.get("REDIS_URL", "") or os.environ.get("CACHE_URL", "")
if _redis_url:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": _redis_url}}
else:
    CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "proflens"}}

RATELIMIT_USE_CACHE = "default"
RATELIMIT_VIEW = "reviews.views.ratelimited"

EMAIL_BACKEND = os.environ.get("EMAIL_BACKEND", "django.core.mail.backends.console.EmailBackend")
DEFAULT_FROM_EMAIL = os.environ.get("DEFAULT_FROM_EMAIL", "noreply@proflens.kg")
EMAIL_HOST = os.environ.get("EMAIL_HOST", "")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "25") or 25)
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "False").lower() in ("1", "true", "yes", "on")
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
PASSWORD_RESET_TIMEOUT = 86400

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
USE_I18N = True
LANGUAGE_CODE = "ru"
LANGUAGES = [("ru", "Русский"), ("ky", "Кыргызча"), ("en", "English")]
LOCALE_PATHS = [BASE_DIR / "locale"]
TIME_ZONE = "Asia/Bishkek"
USE_TZ = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "home"
LOGOUT_REDIRECT_URL = "home"

X_FRAME_OPTIONS = "DENY"
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
SECURE_CROSS_ORIGIN_OPENER_POLICY = "same-origin"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = 1209600

if not DEBUG:
    SECURE_SSL_REDIRECT = os.environ.get("SECURE_SSL_REDIRECT", "True").lower() not in ("0", "false", "no", "off")
    _hsts = int(os.environ.get("SECURE_HSTS_SECONDS", "31536000") or 31536000)
    SECURE_HSTS_SECONDS = _hsts
    SECURE_HSTS_INCLUDE_SUBDOMAINS = os.environ.get("SECURE_HSTS_INCLUDE_SUBDOMAINS", "True").lower() not in ("0", "false", "no", "off")
    SECURE_HSTS_PRELOAD = os.environ.get("SECURE_HSTS_PRELOAD", "True").lower() not in ("0", "false", "no", "off")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    if os.environ.get("SECURE_PROXY_SSL_HEADER", "").lower() in ("1", "true", "yes", "on"):
        SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    _csrf = os.environ.get("CSRF_TRUSTED_ORIGINS", "")
    if _csrf:
        CSRF_TRUSTED_ORIGINS = [o.strip() for o in _csrf.split(",") if o.strip()]
    else:
        CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h not in ("testserver", "localhost", "127.0.0.1")]
else:
    SECURE_SSL_REDIRECT = False
    SECURE_HSTS_SECONDS = 0
    SECURE_HSTS_INCLUDE_SUBDOMAINS = False
    SECURE_HSTS_PRELOAD = False
    SESSION_COOKIE_SECURE = False
    CSRF_COOKIE_SECURE = False

from django.utils.csp import CSP as _CSP
SECURE_CSP = {
    "default-src": [_CSP.SELF],
    "style-src": [_CSP.SELF, "https://fonts.googleapis.com"],
    "font-src": [_CSP.SELF, "https://fonts.gstatic.com"],
    "img-src": [_CSP.SELF, "data:"],
    "script-src": [_CSP.SELF],
}
SECURE_CSP_REPORT_ONLY = {}

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "sanitize": {
            "()": "reviews.logging_filters.SanitizeFilter",
        },
    },
    "formatters": {
        "plain": {"format": "%(levelname)s %(name)s %(message)s"},
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "formatter": "plain",
            "filters": ["sanitize"],
        },
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "reviews": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

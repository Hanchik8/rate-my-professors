# ProfLens — отзывы о преподавателях вузов Кыргызстана

Аналог RateMyProfessors для вузов КР. Интерфейс на русском, кыргызском и английском (по умолчанию `ru`).

## Локальный запуск

```bash
cp .env.example .env          # при необходимости поправьте значения
pip install -r requirements.txt

# вариант A — без БД (in-memory, данные сбрасываются при рестарте)
python manage.py runserver     # http://127.0.0.1:8000
python manage.py test

# вариант B — с PostgreSQL (данные сохраняются)
docker compose up -d           # поднимет Postgres (или см. DATABASE_URL в .env)
python manage.py migrate
python manage.py seed_kg       # залить демо-данные КР
python manage.py createsuperuser
python manage.py runserver
```

### Первый админ

```bash
python manage.py createsuperuser
python manage.py setup_admin_totp <email>   # печатает otpauth://... URL
```

1. Отсканируйте `otpauth://` ссылку (или QR, построенный из неё) в Google Authenticator.
2. Зайдите по адресу `/<ADMIN_URL>` (путь из переменной `ADMIN_URL`, по умолчанию в dev — `/admin/`) и введите код из приложения.

Без подтверждённого TOTP-устройства staff/superuser не попадёт в админку (см. `Admin2FATests`).

### Переменные окружения (.env)

| Переменная | Пример / примечание | Описание |
|---|---|---|
| `SECRET_KEY` | 50+ символов | **Обязательна в prod** (`DEBUG=False` → fail). |
| `DEBUG` | `False` | По умолчанию `False`. Тесты форсируют `True`. |
| `ALLOWED_HOSTS` | `example.kg,www.example.kg` | Через запятую, `*` запрещён в prod. |
| `DATABASE_URL` | `postgres://user:pass@host:5432/db` | SQLite если пусто. |
| `REPO_BACKEND` | `django` | `memory` или `django`; при `DATABASE_URL` по умолчанию `django`. В prod `memory` запрещён. |
| `ADMIN_URL` | `admin-CHANGE-ME-123/` | Путь админки (2FA TOTP обязателен для staff). |
| `EMAIL_BACKEND` | `console`/`smtp` | В prod SMTP; `DEFAULT_FROM_EMAIL`, `EMAIL_HOST*`. |
| `REDIS_URL`/`CACHE_URL` | `redis://...` | В prod Redis для ratelimit/axes; без него `locmem` (в тестах `locmem`). |
| `CSRF_TRUSTED_ORIGINS` | `https://example.kg` | Через запятую; по умолчанию `https://ALLOWED_HOSTS`. |
| `SECURE_*` | `True`/`31536000` | `SECURE_SSL_REDIRECT`, `SECURE_PROXY_SSL_HEADER`, `SECURE_HSTS_SECONDS/INCLUDE_SUBDOMAINS/PRELOAD` |

### Деплой

```bash
# required prod env
export DEBUG=False
export SECRET_KEY="<50+ chars random>"
export ALLOWED_HOSTS="example.kg,www.example.kg"
export DATABASE_URL="postgres://..."
export REPO_BACKEND=django
export ADMIN_URL="admin-$(openssl rand -hex 6)/"
export EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
export REDIS_URL="redis://..."

python manage.py migrate
python manage.py compilemessages
python manage.py check --deploy   # должен быть 0 warnings
gunicorn config.wsgi:application  # behind TLS-terminating proxy (set SECURE_PROXY_SSL_HEADER=True if proxy)
```

Security headers: `X-Frame-Options: DENY`, `nosniff`, `same-origin` referrer/COOP, `SameSite=Lax`, `HttpOnly`, `SESSION_COOKIE_AGE=2 weeks`, `PASSWORD_RESET_TIMEOUT=24h`. CSP: `default-src 'self'`, `script-src 'self'` без `unsafe-inline`.

### i18n

```bash
python manage.py makemessages -l ky -l ru -l en
python manage.py compilemessages             # скомпилировать .mo (требуется в CI)
```

Язык переключается формой `POST /i18n/setlang/` (cookie `django_language`, без сессий).

## Архитектура

`reviews/repository.py` — `InMemoryRepository`, `reviews/models.py` + `reviews/django_repo.py` — `DjangoRepository`, выбор в `reviews/store.py` по `REPO_BACKEND`/`DATABASE_URL`. Views (`reviews/views.py`) работают только через `repo`.

## Правила и модерация

Отзывы и новые преподаватели попадают на модерацию (`pending` → `approved`). Правила: `/rules/`, конфиденциальность: `/privacy/` (удаление аккаунта — отзывы остаются анонимными, см. также `/accounts/delete/`).

## Безопасность

См. `SECURITY.md`. Сообщить об уязвимости: `security@proflens.kg`.

## CI

Workflow `.github/workflows/ci.yml`: Python 3.12 + Postgres, `compilemessages`, тесты `memory`+`django`, `check --deploy` prod-env, `makemigrations --check`, `pip-audit`, `bandit`.

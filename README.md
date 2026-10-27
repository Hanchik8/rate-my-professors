# ProfLens — отзывы о преподавателях вузов Кыргызстана

Аналог RateMyProfessors для вузов КР. Интерфейс на русском, кыргызском и английском (по умолчанию `ru`).

## Локальный запуск

```bash
cp .env.example .env          # при необходимости поправьте значения
pip install -r requirements.txt

# вариант A — без БД (in-memory, данные сбрасываются при рестарте)
python manage.py runserver     # http://127.0.0.1:8000
python manage.py test reviews  # тесты (DEBUG=True берётся из .env)

# вариант B — с PostgreSQL (данные сохраняются)
docker compose up -d           # поднимет Postgres (или см. DATABASE_URL в .env)
python manage.py migrate
python manage.py seed_kg       # все вузы КР из data/universities_kg.json + демо-преподаватели (повторный запуск безопасен)
python manage.py seed_fake --professors 3000 --reviews 30000   # много тестовых данных (не для боевой БД!)
python manage.py seed_fake --wipe --professors 3000 --reviews 30000   # заменить прежние тестовые данные, реальные не трогает
python manage.py createsuperuser
python manage.py runserver
```

### Переменные окружения (.env)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `DEBUG` | `False` | `True` только для разработки |
| `SECRET_KEY` | — | Обязателен при `DEBUG=False` (50+ случайных символов), иначе сайт не запустится |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1` при DEBUG | Обязателен при `DEBUG=False`, через запятую |
| `CSRF_TRUSTED_ORIGINS` | — | `https://ваш-домен` — нужен за HTTPS-прокси |
| `TRUSTED_PROXY_COUNT` | `0` | Сколько прокси перед gunicorn (Caddy/балансировщик = 1). Нужно для HTTPS-заголовка и реального IP в rate limit |
| `REDIS_URL` | — | Общий кэш и счётчики rate limit для всех воркеров |
| `READ_CACHE_SECONDS` | `60` | Сколько секунд кэшировать списки и статистику (0 — выключить) |
| `REQUIRE_EMAIL_VERIFICATION` | `False` | `True` — писать отзывы/голосовать могут только подтвердившие email |
| `EMAIL_HOST`, `EMAIL_HOST_USER`, ... | — | SMTP для писем. Без них письма пишутся в лог |
| `ADMIN_URL` | `admin/` | Путь к админке, в проде лучше спрятать |
| `RATELIMIT_LOGIN` и др. | `10/m` ... | Лимиты POST-запросов, см. `config/settings.py` |
| `DATABASE_URL` | _(пусто — SQLite)_ | `postgres://user:pass@host:port/db` |
| `REPO_BACKEND` | `memory` | `memory` или `django` (ORM). При `DATABASE_URL` по умолчанию `django` |

### i18n

```bash
python manage.py makemessages -l ky -l ru   # собрать строки
python manage.py compilemessages             # скомпилировать .mo
```

Язык переключается формой `POST /i18n/setlang/` (cookie `django_language`, без сессий).

## Архитектура

`reviews/repository.py` — `InMemoryRepository`, `reviews/models.py` + `reviews/django_repo.py` — `DjangoRepository`, выбор в `reviews/store.py` по `REPO_BACKEND`/`DATABASE_URL`. Views (`reviews/views.py`) работают только через `repo`.

## Правила и модерация

Отзывы и новые преподаватели попадают на модерацию (`pending` → `approved`). Правила: ` /rules/`.

## Деплой в продакшен (Docker)

Нужен сервер с Docker (любой VPS с 2+ CPU и 2+ ГБ RAM) и домен, направленный на IP сервера (A-запись).

```bash
git clone <repo> proflens && cd proflens
cp .env.prod.example .env.prod
# откройте .env.prod и заполните: SECRET_KEY, POSTGRES_PASSWORD, ALLOWED_HOSTS, CSRF_TRUSTED_ORIGINS, DOMAIN
python3 -c "import secrets; print(secrets.token_urlsafe(64))"   # готовый SECRET_KEY

# запуск: web (gunicorn) + PostgreSQL + Redis + Caddy (бесплатный HTTPS-сертификат)
docker compose -f docker-compose.prod.yml --env-file .env.prod --profile https up -d --build

docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py createsuperuser
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py seed_kg   # вузы КР (идемпотентно)
```

Что происходит при старте контейнера `web` (`docker-entrypoint.sh`): ждёт базу → `migrate` → gunicorn. Статика собирается при сборке образа и раздаётся WhiteNoise (сжатие + вечный кэш), отдельный nginx не нужен.

Если у хостинга уже есть свой HTTPS-прокси (Render, Railway, облачный балансировщик) — запускайте без `--profile https`, оставьте `TRUSTED_PROXY_COUNT=1` и при необходимости `WEB_BIND=0.0.0.0`. Если перед gunicorn нет никакого прокси — `TRUSTED_PROXY_COUNT=0` (иначе можно подделать IP через `X-Forwarded-For`).

Проверки:

```bash
curl -s https://ваш-домен/healthz        # {"status": "ok", "db": "ok", "cache": "ok"}
docker compose -f docker-compose.prod.yml --env-file .env.prod exec web python manage.py check --deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod logs -f web
```

Обновление: `git pull && docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build`.
Бэкап базы: `docker compose -f docker-compose.prod.yml --env-file .env.prod exec db pg_dump -U proflens proflens > backup.sql`.

### Что сделано для безопасности

* `DEBUG=False` по умолчанию; без надёжного `SECRET_KEY` и `ALLOWED_HOSTS` приложение не стартует.
* HTTPS-редирект, HSTS, secure/HttpOnly cookies, `X-Frame-Options: DENY`, nosniff, Referrer-Policy.
* Проверка паролей (длина, похожесть на email, частые и цифровые пароли).
* Rate limit только на POST (вход, регистрация, отзыв, голос, жалоба, добавление преподавателя) → HTTP 429. Считается по IP клиента, а не по аккаунту, поэтому никто не может заблокировать чужой аккаунт. GET-запросы не ограничиваются.
* Один голос и одна жалоба на отзыв от пользователя, один отзыв на предмет у преподавателя — это гарантирует база (unique constraints), а счётчики обновляются атомарно (`F()`), без гонок.
* Подтверждение email не трогает `is_active`, поэтому не снимает бан.
* В отзывах запрещены ссылки, email и телефоны; имена преподавателей — только буквы.

### Производительность

* Списки преподавателей считаются одним SQL-запросом (`annotate(Avg, Count)`), пагинация на стороне базы.
* Индексы под поиск и страницы, постоянные соединения с БД (`CONN_MAX_AGE`).
* Кэш списков/статистики на `READ_CACHE_SECONDS` (Redis в проде), голоса показываются сразу.
* gunicorn `gthread`: `WEB_CONCURRENCY` процессов × `GUNICORN_THREADS` потоков (`gunicorn.conf.py`).

## Вузы, города и области

Справочник `data/universities_kg.json` содержит все вузы КР (государственные и частные) с названиями на ru/ky/en,
сокращением, городом, областью и сайтом. Источник: портал Министерства образования и науки КР
(kesiptanda.edu.gov.kg, список 74 вузов) и список Национального офиса Erasmus+ на 1.04.2023; ссылки в самом файле.
Ключ записи `code` стабилен: `seed_kg` обновляет вузы по нему (update_or_create), ничего не дублируя.
Области (7) и города республиканского значения (Бишкек, Ош) описаны в `reviews/geo.py`; фильтр на главной
группирует города по областям и сужает список вузов (на сервере, плюс `filters.js` без перезагрузки).

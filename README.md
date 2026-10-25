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

### Переменные окружения (.env)

| Переменная | По умолчанию | Описание |
|---|---|---|
| `SECRET_KEY` | `dev-only-change-me` | Секрет Django (в проде обязателен свой) |
| `DEBUG` | `False` | `True` только для локальной разработки |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Через запятую, напр. `example.com,127.0.0.1`. `*` запрещён в проде |
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

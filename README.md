# ProfLens — отзывы о преподавателях вузов Кыргызстана

Аналог RateMyProfessors для вузов КР. Интерфейс на русском, кыргызском и английском (по умолчанию `ru`).

> **Готовность к продакшену:** проект пока **не готов** к публичному запуску. Аудит, блокеры P0 и
> требования к деплою — [`DEPLOYMENT.md`](DEPLOYMENT.md). Инструкция для владельца и модераторов —
> [`ADMIN_GUIDE.md`](ADMIN_GUIDE.md).

## Локальный запуск

> ⚠️ В текущей версии `.env` **не загружается автоматически**: переменные нужно экспортировать в
> оболочку. Кроме того, `.env.example` задаёт `REPO_BACKEND=memory`, который перекрывает
> `DATABASE_URL`; для PostgreSQL установите `REPO_BACKEND=django`. Подробности — в
> [`DEPLOYMENT.md`](DEPLOYMENT.md), раздел «The data-loss trap».

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
| `SECRET_KEY` | `dev-only-change-me` | Секрет Django |
| `DEBUG` | `True` | `False` в проде |
| `ALLOWED_HOSTS` | `*` | Через запятую, напр. `example.com,127.0.0.1` |
| `DATABASE_URL` | _(пусто — SQLite)_ | `postgres://user:pass@host:port/db` |
| `REPO_BACKEND` | `memory` | `memory` или `django` (ORM). Если переменная пуста, но задан `DATABASE_URL`, выбирается `django`. Явное `memory` имеет приоритет и отключает БД. |

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

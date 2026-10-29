# ProfLens — отзывы о преподавателях вузов Кыргызстана

Аналог RateMyProfessors для вузов Кыргызстана. Интерфейс доступен на русском, кыргызском и английском языках; язык по умолчанию — русский.

## Запуск проекта

1. Установите зависимости из `requirements.txt` и подготовьте файл `.env` на основе `.env.example`.
2. Выберите хранилище данных. Без `DATABASE_URL` приложение использует хранилище в памяти; для PostgreSQL задайте `DATABASE_URL` и настройте доступ к базе.
3. Для PostgreSQL выполните миграции:

   ```bash
   python manage.py migrate
   ```

4. Запустите сервер разработки:

   ```bash
   python manage.py runserver
   ```

   Приложение будет доступно по адресу http://127.0.0.1:8000. В режиме хранилища в памяти данные сбрасываются при перезапуске.

## Подтверждение email и почта (SMTP)

При регистрации аккаунт создаётся неактивным, на указанный адрес приходит 6-значный код (действует 10 минут, 5 попыток, повторная отправка не чаще раза в минуту). После ввода кода на странице `/accounts/signup/verify/` аккаунт активируется и пользователь входит. Если неподтверждённый пользователь пытается войти, страница входа показывает ссылку на ввод кода. Уже существующие аккаунты не затрагиваются.

Почта настраивается через `.env` (см. `.env.example`). Бесплатный вариант по умолчанию — Gmail SMTP: `EMAIL_HOST=smtp.gmail.com`, `EMAIL_PORT=587`, `EMAIL_USE_TLS=True`, `EMAIL_HOST_USER` — адрес Gmail, `EMAIL_HOST_PASSWORD` — пароль приложения Google (Аккаунт Google → Безопасность → Двухэтапная аутентификация → Пароли приложений), `DEFAULT_FROM_EMAIL` — адрес отправителя (если пусто, берётся `EMAIL_HOST_USER`). Пока SMTP не настроен, поставьте `REQUIRE_EMAIL_VERIFICATION=False` — тогда новые аккаунты активируются сразу, как раньше. Значение `auto` включает подтверждение само, как только заполнены `EMAIL_HOST_USER` и `EMAIL_HOST_PASSWORD`. В режиме `DEBUG` без `EMAIL_HOST_USER` письма печатаются в консоль.

## Тесты

Запустите полный набор тестов Django:

```bash
python manage.py test
```

## Структура приложения `reviews/`

- `models.py` — модели Django для данных приложения.
- `views.py` — обработчики запросов и страниц; доступ к данным выполняется через репозиторий.
- `forms.py` — формы и проверка пользовательского ввода.
- `repository.py`, `django_repo.py`, `store.py` — репозитории в памяти и на Django ORM, а также выбор активного хранилища.
- `templates/` — HTML-шаблоны страниц и общие фрагменты интерфейса.
- `static/` — CSS-стили и JavaScript-файлы.
- `locale/` — файлы переводов интерфейса.
- `middleware.py` — промежуточная обработка HTTP-запросов и ответов.
- `throttle.py` — ограничение частоты запросов.
- `sanitize.py` — очистка и безопасная обработка пользовательского ввода.

## Правила и модерация

Отзывы и новые преподаватели проходят модерацию: `pending` → `approved`. Правила публикации доступны по адресу `/rules/`.

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
* Подтверждение email кодом активирует только аккаунты, ожидающие подтверждения (есть запись `EmailVerification`), поэтому не снимает бан.
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

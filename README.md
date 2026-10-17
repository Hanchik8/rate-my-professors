# ProfLens (Django MVP, no database)

    pip install -r requirements.txt
    python manage.py runserver      # http://127.0.0.1:8000
    python manage.py test           # smoke tests, no DB needed

Data lives in memory (`reviews/repository.py`), seeded with fictional demo data
(`reviews/seed.py`). Everything resets on restart.

## Connecting PostgreSQL later
1. Write Django models mirroring your schema (schools, departments, professors,
   courses, reviews, tags...) and `pip install psycopg[binary]`.
2. Fill in `DATABASES` in `config/settings.py` (ENGINE `django.db.backends.postgresql`).
3. Run `makemigrations` and `migrate`.
4. Add a `DjangoRepository` with the same methods as `InMemoryRepository`
   (`search`, `stats`, `reviews_for`, `add_review`, `vote`, ...) and switch
   `reviews/store.py` to use it. Views and templates stay as they are.
5. Then add `django.contrib.auth`, `sessions` and `admin` for real accounts and moderation.

## Not in the MVP
Accounts, one-vote-per-user, add-professor form, moderation/reports, school pages.

# ---- ProfLens production image ----
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# dependencies first: this layer is cached until requirements.txt changes
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# static files are collected at build time (compressed + hashed by WhiteNoise).
# A throwaway key is used only for this step; the real one comes from .env at runtime.
RUN DEBUG=False SECRET_KEY=build-only-$(python -c "import secrets;print(secrets.token_urlsafe(64))") \
    ALLOWED_HOSTS=build python manage.py collectstatic --noinput -v0

# run as an unprivileged user
RUN useradd --system --uid 10001 --home /app proflens && chown -R proflens /app/staticfiles
USER proflens

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status == 200 else 1)"

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "-c", "gunicorn.conf.py"]

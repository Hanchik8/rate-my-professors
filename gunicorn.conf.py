"""Gunicorn settings. Every value can be overridden with an environment variable."""
import multiprocessing
import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
# processes x threads = requests handled at the same time.
# default: 2 x CPU + 1 processes, 4 threads each (good for a DB-bound Django app)
workers = int(os.environ.get("WEB_CONCURRENCY", multiprocessing.cpu_count() * 2 + 1))
threads = int(os.environ.get("GUNICORN_THREADS", 4))
worker_class = "gthread"
timeout = int(os.environ.get("GUNICORN_TIMEOUT", 30))
graceful_timeout = 20
keepalive = 5
# restart workers now and then so a slow memory leak can never take the site down
max_requests = 2000
max_requests_jitter = 200
# load the app once in the master process: faster start, less memory
preload_app = True
accesslog = "-" if os.environ.get("GUNICORN_ACCESS_LOG", "1") == "1" else None
errorlog = "-"
loglevel = os.environ.get("GUNICORN_LOG_LEVEL", "info")
# trust X-Forwarded-* only from the reverse proxy network (Caddy in docker compose)
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
worker_tmp_dir = "/dev/shm" if os.path.isdir("/dev/shm") else None
# gunicorn 25+: control socket in a writable place (the app dir is read-only for the app user)
control_socket = "/tmp/gunicorn.ctl"

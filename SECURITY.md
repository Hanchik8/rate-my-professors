# Security Policy

## Reporting
Email: security@proflens.kg. We respond within 72h. Please include steps to reproduce and avoid public disclosure before a fix is released.

## Supported versions
Only `main` / latest deploy is supported.

## Hardening summary
- `DEBUG=False` by default; fail-safe: missing `SECRET_KEY` (<50), `ALLOWED_HOSTS=*`, or `REPO_BACKEND=memory` in prod → `ImproperlyConfigured`.
- HSTS 1 year + subdomains + preload, `SECURE_SSL_REDIRECT`/`SECURE_PROXY_SSL_HEADER` via env, `SESSION/CSR F_COOKIE_SECURE`, `HTTPONLY`, `SameSite=Lax`, `X-Frame-Options: DENY`.
- CSP via Django (built-in): `default-src 'self'`, `style-src 'self' + fonts.googleapis.com`, `font-src 'self' + fonts.gstatic.com`, `script-src 'self'` (no `unsafe-inline`).
- Admin URL via `ADMIN_URL` env (not `/admin/`).
- Passwords: Argon2, validators `min_length=10` + similarity/common/numeric, email confirmation 24h (console in dev, SMTP in prod via `EMAIL_*`).
- `django-axes` 5 fails / 1h by `login+IP`, `django-otp` TOTP for admin.
- Ratelimit (locmem in tests, Redis in prod via `REDIS_URL`/`CACHE_URL`): signup 5/h IP, review 5/d user, vote 60/h, report 20/h, add-professor 5/d.
- DB constraints: `CheckConstraint` 1..5, `UniqueConstraint(Lower(course), professor, author)`.

## Dependencies
Run `pip-audit` and `bandit` before release; see CI workflow `ci.yml`.

import os

def _trusted_count():
    try:
        return int(os.environ.get("TRUSTED_PROXY_COUNT", "0") or 0)
    except ValueError:
        return 0

def client_ip(request):
    n = _trusted_count()
    if n <= 0:
        return request.META.get("REMOTE_ADDR", "")
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if not xff:
        return request.META.get("REMOTE_ADDR", "")
    parts = [p.strip() for p in xff.split(",") if p.strip()]
    if not parts:
        return request.META.get("REMOTE_ADDR", "")
    if len(parts) >= n:
        return parts[-n]
    return parts[0]

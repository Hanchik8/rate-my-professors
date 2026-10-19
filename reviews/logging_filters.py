import logging
import re

_SENSITIVE_RE = re.compile(
    r"(password|passwd|pwd|secret|token|email)[^\n]*",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

class SanitizeFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        # redact emails and passwords
        msg = _EMAIL_RE.sub("[redacted-email]", msg)
        msg = _SENSITIVE_RE.sub(r"\1=[redacted]", msg)
        record.msg = msg
        record.args = ()
        return True

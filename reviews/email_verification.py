"""Email confirmation with a short numeric code sent at signup.

A new account stays inactive until its owner types the 6-digit code that was
mailed to them.  Only an HMAC of the code is stored; codes expire after a few
minutes, a handful of wrong guesses voids the code, and a fresh code can be
requested at most once per resend interval.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.translation import gettext as _

from .models import EmailVerification

logger = logging.getLogger(__name__)

CODE_LENGTH = 6

OK = "ok"
WRONG = "wrong"
EXPIRED = "expired"
LOCKED = "locked"
MISSING = "missing"


def is_required():
    """Return whether new accounts must confirm their email address."""
    return getattr(settings, "REQUIRE_EMAIL_VERIFICATION", True)


def _ttl():
    return timedelta(seconds=getattr(settings, "EMAIL_VERIFICATION_CODE_TTL", 600))


def max_attempts():
    return getattr(settings, "EMAIL_VERIFICATION_MAX_ATTEMPTS", 5)


def resend_interval():
    return getattr(settings, "EMAIL_VERIFICATION_RESEND_INTERVAL", 60)


def generate_code():
    """Return a cryptographically random zero-padded 6-digit code."""
    return str(secrets.randbelow(10**CODE_LENGTH)).zfill(CODE_LENGTH)


def hash_code(user, code):
    """Keyed hash of ``code`` bound to ``user`` so stored values are useless alone."""
    key = settings.SECRET_KEY.encode()
    msg = f"email-verification:{user.pk}:{code}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def seconds_until_resend(record, now=None):
    """Return how many seconds remain before another code may be sent."""
    if record is None:
        return 0
    now = now or timezone.now()
    ready_at = record.last_sent_at + timedelta(seconds=resend_interval())
    return max(0, int((ready_at - now).total_seconds() + 0.999))


def _send(user, code):
    minutes = int(_ttl().total_seconds() // 60)
    subject = _("Код подтверждения ProfLens: %(code)s") % {"code": code}
    body = _(
        "Ваш код подтверждения ProfLens: %(code)s\n\n"
        "Код действует %(minutes)s минут. Если вы не регистрировались на ProfLens, "
        "просто проигнорируйте это письмо."
    ) % {"code": code, "minutes": minutes}
    send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [user.email])


def issue_code(user):
    """Create or replace the user's code and email it.

    Returns ``True`` when the email was handed to the backend, ``False`` when
    sending failed (the code is still stored so a resend can be attempted).
    """
    code = generate_code()
    now = timezone.now()
    EmailVerification.objects.update_or_create(
        user=user,
        defaults={
            "code_hash": hash_code(user, code),
            "expires_at": now + _ttl(),
            "attempts": 0,
            "last_sent_at": now,
        },
    )
    try:
        _send(user, code)
    except Exception:  # SMTP misconfiguration must not crash signup.
        logger.exception("Failed to send verification email to user %s", user.pk)
        return False
    return True


@dataclass
class ResendResult:
    sent: bool
    wait: int = 0
    delivered: bool = True


def resend_code(user):
    """Send a fresh code unless the resend interval has not elapsed yet."""
    record = EmailVerification.objects.filter(user=user).first()
    wait = seconds_until_resend(record)
    if wait:
        return ResendResult(sent=False, wait=wait)
    return ResendResult(sent=True, delivered=issue_code(user))


def check_code(user, code):
    """Validate ``code`` for ``user`` and return one of the status constants.

    On success the record is deleted; the caller activates the account.
    """
    record = EmailVerification.objects.filter(user=user).first()
    if record is None or not record.code_hash:
        return MISSING
    if timezone.now() >= record.expires_at:
        return EXPIRED
    if record.attempts >= max_attempts():
        return LOCKED
    if hmac.compare_digest(record.code_hash, hash_code(user, (code or "").strip())):
        record.delete()
        return OK
    record.attempts += 1
    if record.attempts >= max_attempts():
        record.code_hash = ""
        record.save(update_fields=["attempts", "code_hash"])
        return LOCKED
    record.save(update_fields=["attempts"])
    return WRONG

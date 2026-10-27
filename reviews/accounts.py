"""Email verification.

The link in the letter contains a signed one-time token (same technique as
Django's password reset). Confirming only sets AccountProfile.email_verified;
it never touches User.is_active, so a banned user stays banned.
"""
import functools
import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.tokens import PasswordResetTokenGenerator
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.utils.translation import gettext as _

from .models import AccountProfile

logger = logging.getLogger(__name__)


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "reviews.accounts.EmailVerificationTokenGenerator"

    def _make_hash_value(self, user, timestamp):
        profile = get_profile(user)
        # token stops working once the email is verified or the email changes
        return f"{user.pk}{user.email}{profile.email_verified}{timestamp}"


token_generator = EmailVerificationTokenGenerator()


def get_profile(user):
    profile, _ = AccountProfile.objects.get_or_create(user=user)
    return profile


def is_verified(user):
    if not user.is_authenticated:
        return False
    if user.is_staff or user.is_superuser:
        return True
    return get_profile(user).email_verified


def send_verification_email(request, user):
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    path = reverse("verify_email", args=[uid, token_generator.make_token(user)])
    base = settings.SITE_URL or request.build_absolute_uri("/").rstrip("/")
    link = base + path
    try:
        send_mail(
            subject=_("Подтвердите email на ProfLens"),
            message=_("Здравствуйте! Чтобы подтвердить email, откройте ссылку:\n\n%(link)s\n\n"
                      "Если вы не регистрировались на ProfLens, просто проигнорируйте это письмо.") % {"link": link},
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
        return True
    except Exception:  # noqa: BLE001 - SMTP problems must not break signup
        logger.exception("could not send verification email")
        return False


def verified_required(view):
    """When REQUIRE_EMAIL_VERIFICATION=True, block POSTs of users without a confirmed email."""
    @functools.wraps(view)
    def wrapped(request, *args, **kwargs):
        if (settings.REQUIRE_EMAIL_VERIFICATION and request.method == "POST"
                and request.user.is_authenticated and not is_verified(request.user)):
            messages.warning(request, _("Сначала подтвердите email — мы отправили письмо со ссылкой."))
            return redirect("verification_needed")
        return view(request, *args, **kwargs)
    return wrapped

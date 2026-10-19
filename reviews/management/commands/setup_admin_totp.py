from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django_otp.plugins.otp_totp.models import TOTPDevice


class Command(BaseCommand):
    help = "Creates TOTPDevice for admin and prints otpauth:// URL for Google Authenticator"

    def add_arguments(self, parser):
        parser.add_argument("email", help="Email (username) of admin")

    def handle(self, *args, **options):
        email = options["email"]
        User = get_user_model()
        try:
            user = User.objects.get(email__iexact=email)
        except User.DoesNotExist:
            try:
                user = User.objects.get(username__iexact=email)
            except User.DoesNotExist:
                raise CommandError(f"User {email} not found")
        if not user.is_staff:
            raise CommandError("User is not staff")
        device, created = TOTPDevice.objects.get_or_create(user=user, name="default", defaults={"confirmed": False})
        if not created and device.confirmed:
            self.stdout.write(self.style.WARNING(f"TOTP already configured for {email}. URL: {device.config_url}"))
            return
        if not device.confirmed:
            device.confirmed = True
            device.save(update_fields=["confirmed"])
        url = device.config_url
        self.stdout.write(url)
        self.stdout.write(self.style.SUCCESS(f"TOTP for {email} created. Add to Google Authenticator: {url}"))

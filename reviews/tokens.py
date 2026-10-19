from django.contrib.auth.tokens import PasswordResetTokenGenerator

class EmailConfirmTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "proflens.email_confirm"

    def _make_hash_value(self, user, timestamp):
        # Include is_active so token becomes invalid after confirmation or ban
        return f"{user.pk}{user.password}{timestamp}{user.is_active}"

email_confirm_token = EmailConfirmTokenGenerator()

from django.contrib.auth.tokens import PasswordResetTokenGenerator

class EmailConfirmTokenGenerator(PasswordResetTokenGenerator):
    pass

email_confirm_token = EmailConfirmTokenGenerator()

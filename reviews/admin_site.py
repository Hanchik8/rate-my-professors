from django_otp.admin import OTPAdminSite

class ProfLensAdminSite(OTPAdminSite):
    site_header = "ProfLens — админка"
    site_title = "ProfLens"
    index_title = "Панель"

admin_site = ProfLensAdminSite(name="otp_admin")
# Re-register default admin models on OTP site
# Auth User/Group are auto-registered by django contrib; we just need our app models
# reviews/admin.py will register on this site via `admin_site.register`

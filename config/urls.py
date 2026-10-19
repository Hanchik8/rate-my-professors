from django.conf import settings
from django.urls import include, path
from reviews.admin_site import admin_site

urlpatterns = [
    path(settings.ADMIN_URL, admin_site.urls),
    path("i18n/", include("django.conf.urls.i18n")),
    path("", include("reviews.urls")),
]

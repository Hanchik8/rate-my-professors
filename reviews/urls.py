from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("rules/", views.rules, name="rules"),
    path("professors/add/", views.add_professor, name="add_professor"),
    path("schools/<str:slug>/", views.school_detail, name="school_detail"),
    path("professors/<str:slug>/", views.professor_detail, name="professor"),
    path("professors/<str:slug>/rate/", views.review_new, name="review_new"),
    path("reviews/<str:review_id>/vote/", views.review_vote, name="review_vote"),
    path("reviews/<str:review_id>/report/", views.review_report, name="review_report"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/login/", views.login_view, name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/verify/<str:uidb64>/<str:token>/", views.verify_email, name="verify_email"),
    path("accounts/verify/", views.verification_needed, name="verification_needed"),
]

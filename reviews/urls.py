from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy
from .throttle import rate_limit

from . import views
from .views import SafeLogoutView, ThrottledLoginView

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("healthz", views.healthz, name="healthz"),
    path("rules/", views.rules, name="rules"),
    path("about/", views.about, name="about"),
    path("professors/add/", views.add_professor, name="add_professor"),
    path("compare/", views.compare, name="compare"),
    path("schools/<str:slug>/", views.school_detail, name="school_detail"),
    path("professors/<str:slug>/", views.professor_detail, name="professor"),
    path("professors/<str:slug>/rate/", views.review_new, name="review_new"),
    path("reviews/<str:review_id>/vote/", views.review_vote, name="review_vote"),
    path("reviews/<str:review_id>/report/", views.review_report, name="review_report"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/signup/verify/", views.signup_verify, name="signup_verify"),
    path("accounts/profile/", views.profile, name="profile"),
    path("reviews/<str:review_id>/edit/", views.review_edit, name="review_edit"),
    path("reviews/<str:review_id>/delete/", views.review_delete, name="review_delete"),
    path("accounts/login/", ThrottledLoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/password_reset/", rate_limit("login")(auth_views.PasswordResetView.as_view(
        template_name="registration/password_reset_form.html",
        email_template_name="registration/password_reset_email.html",
        subject_template_name="registration/password_reset_subject.txt",
        success_url=reverse_lazy("password_reset_done"),
    )), name="password_reset"),
    path("accounts/password_reset/done/", auth_views.PasswordResetDoneView.as_view(
        template_name="registration/password_reset_done.html",
    ), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(
        template_name="registration/password_reset_confirm.html",
        success_url=reverse_lazy("password_reset_complete"),
    ), name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(
        template_name="registration/password_reset_complete.html",
    ), name="password_reset_complete"),
    path("accounts/logout/", SafeLogoutView.as_view(), name="logout"),
]

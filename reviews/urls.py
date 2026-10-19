from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

handler429 = "reviews.views.ratelimited"

urlpatterns = [
    path("", views.home, name="home"),
    path("schools/", views.school_list, name="school_list"),
    path("rules/", views.rules, name="rules"),
    path("privacy/", views.privacy, name="privacy"),
    path("accounts/delete/", views.delete_account, name="delete_account"),
    path("accounts/confirm/<str:uidb64>/<str:token>/", views.confirm_email, name="confirm_email"),
    path("professors/add/", views.add_professor, name="add_professor"),
    path("schools/<str:slug>/", views.school_detail, name="school_detail"),
    path("professors/<str:slug>/", views.professor_detail, name="professor"),
    path("professors/<str:slug>/rate/", views.review_new, name="review_new"),
    path("reviews/<str:review_id>/vote/", views.review_vote, name="review_vote"),
    path("reviews/<str:review_id>/report/", views.review_report, name="review_report"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/password-reset/", auth_views.PasswordResetView.as_view(template_name="registration/password_reset.html"), name="password_reset"),
    path("accounts/password-reset/done/", auth_views.PasswordResetDoneView.as_view(template_name="registration/password_reset_done.html"), name="password_reset_done"),
    path("accounts/reset/<uidb64>/<token>/", auth_views.PasswordResetConfirmView.as_view(template_name="registration/password_reset_confirm.html"), name="password_reset_confirm"),
    path("accounts/reset/done/", auth_views.PasswordResetCompleteView.as_view(template_name="registration/password_reset_complete.html"), name="password_reset_complete"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(template_name="registration/password_change.html"), name="password_change"),
    path("accounts/password-change/done/", auth_views.PasswordChangeDoneView.as_view(template_name="registration/password_change_done.html"), name="password_change_done"),
]

# 2FA for admin staff is enforced via AdminSite override (reviews/admin.py)

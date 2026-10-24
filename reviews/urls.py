from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("health/", views.health, name="health"),
    path("rules/", views.rules, name="rules"),
    path("professors/add/", views.add_professor, name="add_professor"),
    path("schools/<str:slug>/", views.school_detail, name="school_detail"),
    path("professors/<str:slug>/", views.professor_detail, name="professor"),
    path("professors/<str:slug>/rate/", views.review_new, name="review_new"),
    path("reviews/<str:review_id>/vote/", views.review_vote, name="review_vote"),
    path("reviews/<str:review_id>/report/", views.review_report, name="review_report"),
    path("accounts/signup/", views.signup, name="signup"),
    path("accounts/login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
]

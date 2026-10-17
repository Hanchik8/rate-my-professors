from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("professors/<slug:slug>/", views.professor_detail, name="professor"),
    path("professors/<slug:slug>/rate/", views.review_new, name="review_new"),
    path("reviews/<str:review_id>/vote/", views.review_vote, name="review_vote"),
]

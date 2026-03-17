from django.urls import path

from api.views.users import UsersListView, UsersDetailView
from api.views.posts import PostsListView, PostsDetailView
from api.views.login import UsersLoginView

urlpatterns = [
    path("users/login", UsersLoginView.as_view(), name="users-login"),
    path("users", UsersListView.as_view(), name="users-list"),
    path("users/<str:pk>", UsersDetailView.as_view(), name="users-detail"),
    path("posts", PostsListView.as_view(), name="posts-list"),
    path("posts/<str:pk>", PostsDetailView.as_view(), name="posts-detail"),
]

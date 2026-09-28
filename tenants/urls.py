from django.urls import path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register("team", views.TeamViewSet, basename="team")
router.register("api-keys", views.APIKeyViewSet, basename="api-key")

urlpatterns = [
    path("businesses/", views.MyBusinessesView.as_view(), name="my-businesses"),
    path("business/", views.CurrentBusinessView.as_view(), name="current-business"),
    path("audit-logs/", views.AuditLogView.as_view(), name="audit-logs"),
    *router.urls,
]

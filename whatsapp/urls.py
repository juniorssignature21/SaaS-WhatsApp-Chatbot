from rest_framework.routers import DefaultRouter

from .views import WhatsAppAccountViewSet

router = DefaultRouter()
router.register("accounts", WhatsAppAccountViewSet, basename="whatsapp-account")
urlpatterns = router.urls

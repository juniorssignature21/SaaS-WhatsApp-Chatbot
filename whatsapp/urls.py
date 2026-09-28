from rest_framework.routers import DefaultRouter

from .views import MessageTemplateViewSet, WhatsAppAccountViewSet

router = DefaultRouter()
router.register("accounts", WhatsAppAccountViewSet, basename="whatsapp-account")
router.register("templates", MessageTemplateViewSet, basename="whatsapp-template")
urlpatterns = router.urls

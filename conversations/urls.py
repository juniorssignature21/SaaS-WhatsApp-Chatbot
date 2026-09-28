from rest_framework.routers import DefaultRouter

from .views import ConversationViewSet, MessageMediaViewSet

router = DefaultRouter()
router.register("conversations", ConversationViewSet, basename="conversation")
router.register("message-media", MessageMediaViewSet, basename="message-media")
urlpatterns = router.urls

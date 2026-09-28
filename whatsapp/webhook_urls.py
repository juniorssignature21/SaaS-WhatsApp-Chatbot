from django.urls import path

from .webhooks import whatsapp_webhook

urlpatterns = [path("", whatsapp_webhook, name="whatsapp-webhook")]

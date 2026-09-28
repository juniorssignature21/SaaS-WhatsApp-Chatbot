from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def healthz(request):
    return JsonResponse({"status": "ok"})


api_v1 = [
    path("auth/", include("accounts.urls")),
    path("", include("tenants.urls")),
    path("", include("customers.urls")),
    path("", include("conversations.urls")),
    path("whatsapp/", include("whatsapp.urls")),
    path("chatbot/", include("chatbot.urls")),
    path("knowledge/", include("knowledge.urls")),
    path("tools/", include("tools.urls")),
    path("billing/", include("billing.urls")),
    path("analytics/", include("analytics.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz),
    path("api/v1/", include(api_v1)),
    path("webhooks/whatsapp/", include("whatsapp.webhook_urls")),
]

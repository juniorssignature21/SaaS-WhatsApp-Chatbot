from django.contrib import admin
from django.http import HttpResponse, JsonResponse
from django.urls import include, path
from django.views.generic import RedirectView

from billing.webhooks import paystack_webhook


def healthz(request):
    return JsonResponse({"status": "ok"})


def favicon(request):
    return HttpResponse(status=204)


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
    path("notifications/", include("notifications.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz/", healthz),
    path("favicon.ico", favicon),
    path("api/v1/", include(api_v1)),
    path("webhooks/whatsapp/", include("whatsapp.webhook_urls")),
    path("webhooks/paystack/", paystack_webhook, name="paystack-webhook"),
    path("app/", include("dashboard.urls")),
    path("", RedirectView.as_view(pattern_name="dashboard:overview", permanent=False)),
]

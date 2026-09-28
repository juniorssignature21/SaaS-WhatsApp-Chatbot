from django.urls import path

from . import views

urlpatterns = [
    path("plans/", views.PlanListView.as_view(), name="plans"),
    path("subscription/", views.SubscriptionView.as_view(), name="subscription"),
    path("usage/", views.UsageHistoryView.as_view(), name="usage-history"),
]

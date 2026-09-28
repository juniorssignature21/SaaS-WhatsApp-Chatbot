from django.urls import path

from . import views

urlpatterns = [
    path("plans/", views.PlanListView.as_view(), name="plans"),
    path("subscription/", views.SubscriptionView.as_view(), name="subscription"),
    path("usage/", views.UsageHistoryView.as_view(), name="usage-history"),
    path("checkout/", views.CheckoutView.as_view(), name="billing-checkout"),
    path("verify/", views.VerifyPaymentView.as_view(), name="billing-verify"),
    path("cancel/", views.CancelSubscriptionView.as_view(), name="billing-cancel"),
    path("payments/", views.PaymentListView.as_view(), name="billing-payments"),
]

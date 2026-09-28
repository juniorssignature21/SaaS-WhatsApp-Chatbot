from django.test import TestCase

from common.testing import api_client, make_business

from .services import record_usage


class UsageTests(TestCase):
    def test_record_usage_accumulates(self):
        business, owner = make_business()
        record_usage(business, messages_in=2)
        record_usage(business, messages_in=3, input_tokens=100)
        usage = business.usage_records.get()
        self.assertEqual((usage.messages_in, usage.input_tokens), (5, 100))
        with self.assertRaises(ValueError):
            record_usage(business, bogus=1)

        data = api_client(owner).get("/api/v1/billing/subscription/").data
        self.assertEqual(data["usage"]["messages_in"], 5)
        overview = api_client(owner).get("/api/v1/analytics/overview/")
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.data["messages"]["received"], 5)


import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
from datetime import timedelta  # noqa: E402
from unittest import mock  # noqa: E402

from django.test import Client  # noqa: E402
from django.utils import timezone  # noqa: E402

from .models import Payment, Plan, Subscription  # noqa: E402
from .services import expire_subscriptions  # noqa: E402


def paystack_post(event):
    body = json.dumps(event).encode()
    signature = hmac.new(b"sk_test_paystack", body, hashlib.sha512).hexdigest()
    return Client().post("/webhooks/paystack/", data=body, content_type="application/json",
                         HTTP_X_PAYSTACK_SIGNATURE=signature)


class PaystackTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Payer", plan="starter")
        self.plan = Plan.objects.get(code="business")
        with mock.patch("billing.paystack._request",
                        return_value={"authorization_url": "https://checkout.paystack.com/abc"}) as init:
            response = api_client(self.owner).post("/api/v1/billing/checkout/", {"plan": "business"})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.data["authorization_url"], "https://checkout.paystack.com/abc")
        sent = init.call_args.kwargs["json"]
        self.assertEqual(sent["amount"], 5_000_000)  # NGN 50,000 in kobo
        self.reference = response.data["reference"]

    def charge(self, amount=5_000_000, reference=None, status="success"):
        return {"event": "charge.success", "data": {
            "reference": reference or self.reference, "status": status, "amount": amount, "currency": "NGN",
            "paid_at": "2026-09-01T10:00:00Z", "customer": {"customer_code": "CUS_1"}}}

    def test_webhook_activates_plan_once(self):
        self.assertEqual(paystack_post(self.charge()).status_code, 200)
        self.assertEqual(paystack_post(self.charge()).status_code, 200)  # retry is idempotent
        subscription = Subscription.objects.get(business=self.business)
        self.assertEqual((subscription.plan.code, subscription.status), ("business", "ACTIVE"))
        self.assertEqual(subscription.current_period_end - subscription.current_period_start, timedelta(days=30))
        self.assertEqual(Payment.objects.get().status, "SUCCESS")

    def test_rejects_bad_signature_and_underpayment(self):
        body = json.dumps(self.charge()).encode()
        forged = Client().post("/webhooks/paystack/", data=body, content_type="application/json",
                               HTTP_X_PAYSTACK_SIGNATURE="deadbeef")
        self.assertEqual(forged.status_code, 403)
        paystack_post(self.charge(amount=100))
        self.assertEqual(Subscription.objects.get(business=self.business).plan.code, "starter")

    def test_renewal_and_cancellation_flow(self):
        paystack_post(self.charge())
        paystack_post({"event": "subscription.create", "data": {
            "subscription_code": "SUB_1", "email_token": "tok", "customer": {"customer_code": "CUS_1"}}})
        first_end = Subscription.objects.get(business=self.business).current_period_end
        paystack_post(self.charge(reference="renewal-1"))  # Paystack-generated reference
        subscription = Subscription.objects.get(business=self.business)
        self.assertEqual(subscription.current_period_end, first_end + timedelta(days=30))
        self.assertEqual(Payment.objects.count(), 2)

        with mock.patch("billing.paystack._request", return_value={}) as disable:
            response = api_client(self.owner).post("/api/v1/billing/cancel/")
        self.assertTrue(response.data["cancel_at_period_end"])
        self.assertEqual(disable.call_args.kwargs["json"], {"code": "SUB_1", "token": "tok"})
        expire_subscriptions(now=subscription.current_period_end + timedelta(days=10))
        self.assertEqual(Subscription.objects.get(business=self.business).status, "CANCELED")

    def test_callback_verification(self):
        with mock.patch("billing.paystack._request", return_value=self.charge()["data"]):
            response = api_client(self.owner).post("/api/v1/billing/verify/", {"reference": self.reference})
        self.assertEqual(response.data["status"], "SUCCESS")

    def test_trial_expiry_pauses_ai(self):
        from .services import ai_quota_available

        subscription = self.business.subscription
        subscription.trial_ends_at = timezone.now() - timedelta(days=1)
        subscription.save()
        self.assertEqual(expire_subscriptions(), 1)
        self.assertFalse(ai_quota_available(self.business))

    def test_only_owner_can_checkout(self):
        from common.testing import add_member
        from tenants.models import Role

        admin = add_member(self.business, Role.ADMIN)
        self.assertEqual(api_client(admin).post("/api/v1/billing/checkout/", {"plan": "business"}).status_code, 403)

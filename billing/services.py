import logging
import secrets
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from . import paystack
from .models import Payment, Plan, Subscription, UsageRecord

logger = logging.getLogger(__name__)

DEFAULT_PLAN_CODE = "starter"


def current_period(now=None):
    now = now or timezone.now()
    return now.date().replace(day=1)


def record_usage(business, **increments):
    """Atomically add to this month's usage counters."""
    increments = {k: v for k, v in increments.items() if v}
    unknown = set(increments) - set(UsageRecord.COUNTERS)
    if unknown:
        raise ValueError(f"Unknown usage counters: {sorted(unknown)}")
    if not increments:
        return
    period = current_period()
    business_id = getattr(business, "pk", business)
    updated = UsageRecord.objects.filter(business_id=business_id, period=period).update(
        **{k: F(k) + v for k, v in increments.items()}
    )
    if not updated:
        try:
            with transaction.atomic():
                UsageRecord.objects.create(business_id=business_id, period=period, **increments)
        except IntegrityError:
            UsageRecord.objects.filter(business_id=business_id, period=period).update(
                **{k: F(k) + v for k, v in increments.items()}
            )


def get_usage(business, period=None):
    record = UsageRecord.objects.filter(business=business, period=period or current_period()).first()
    return record or UsageRecord(business=business, period=period or current_period())


def start_default_subscription(business):
    plan = Plan.objects.filter(code=DEFAULT_PLAN_CODE).first()
    if plan is None:
        plan = Plan.objects.create(code=DEFAULT_PLAN_CODE, name="Starter")
    return Subscription.objects.create(
        business=business, plan=plan, status=Subscription.Status.TRIALING,
        trial_ends_at=timezone.now() + timedelta(days=settings.TRIAL_DAYS),
    )


def get_plan(business):
    subscription = Subscription.objects.select_related("plan").filter(business=business).first()
    return subscription.plan if subscription else None


def has_feature(business, feature):
    plan = get_plan(business)
    return bool(plan and plan.has_feature(feature))


def ai_quota_available(business):
    """True if the business may receive another AI response this month."""
    subscription = Subscription.objects.select_related("plan").filter(business=business).first()
    if subscription is None or not subscription.is_usable:
        return False
    limit = subscription.plan.monthly_ai_responses
    if limit is None:
        return True
    return get_usage(business).ai_responses < limit


def check_limit(business, limit_field, current_count):
    """True if adding one more item keeps the business within its plan limit."""
    plan = get_plan(business)
    if plan is None:
        return False
    limit = getattr(plan, limit_field)
    return limit is None or current_count < limit


# --- Payments (Paystack) -------------------------------------------------------

def start_checkout(business, plan, email, callback_url):
    """Create a pending payment and return Paystack's hosted checkout URL."""
    if plan.price <= 0:
        raise paystack.PaystackError("This plan cannot be bought online; contact sales.")
    reference = f"sub_{business.id}_{secrets.token_hex(8)}"
    payment = Payment.objects.create(
        business=business, plan=plan, reference=reference, amount=plan.price, currency=plan.currency,
    )
    data = paystack.initialize_transaction(
        email=email, amount=plan.price, reference=reference, callback_url=callback_url,
        plan_code=plan.paystack_plan_code, metadata={"business_id": business.id, "plan": plan.code},
    )
    return data["authorization_url"], payment


def _paid_at(data):
    return parse_datetime(data.get("paid_at") or data.get("paidAt") or "") or timezone.now()


def _activate(subscription, plan, paid_at, customer_code=""):
    renewing = subscription.status == Subscription.Status.ACTIVE and subscription.plan_id == plan.id
    # Renewals extend the paid period; new or changed plans start now.
    start = max(paid_at, subscription.current_period_end or paid_at) if renewing else paid_at
    subscription.plan = plan
    subscription.status = Subscription.Status.ACTIVE
    subscription.current_period_start = start
    subscription.current_period_end = start + timedelta(days=plan.interval_days)
    subscription.cancel_at_period_end = False
    if customer_code:
        subscription.paystack_customer_code = customer_code
    subscription.save()


@transaction.atomic
def confirm_payment(reference, data=None):
    """Apply a successful Paystack transaction exactly once. Returns the Payment or None."""
    payment = Payment.objects.select_for_update(of=("self",)).select_related("plan").filter(reference=reference).first()
    if payment is None:
        return None
    if payment.status == Payment.Status.SUCCESS:
        return payment
    data = data if data is not None else paystack.verify_transaction(reference)
    expected = paystack.to_subunit(payment.amount)
    if (data.get("status") != "success" or int(data.get("amount", 0)) < expected
            or data.get("currency", payment.currency) != payment.currency):
        payment.status = Payment.Status.FAILED if data.get("status") in {"failed", "abandoned"} else payment.status
        payment.raw = data
        payment.save(update_fields=["status", "raw"])
        return payment
    payment.status = Payment.Status.SUCCESS
    payment.paid_at = _paid_at(data)
    payment.raw = data
    payment.save(update_fields=["status", "paid_at", "raw"])
    subscription = Subscription.objects.select_for_update(of=("self",)).get(business=payment.business)
    customer_code = (data.get("customer") or {}).get("customer_code", "")
    _activate(subscription, payment.plan, payment.paid_at, customer_code)
    return payment


@transaction.atomic
def _record_renewal(data):
    """A recurring charge Paystack made for an existing subscription."""
    customer_code = (data.get("customer") or {}).get("customer_code", "")
    subscription = (
        Subscription.objects.select_for_update(of=("self",)).select_related("plan")
        .filter(paystack_customer_code=customer_code).exclude(paystack_customer_code="").first()
    )
    if subscription is None or data.get("status") != "success":
        return None
    payment, created = Payment.objects.get_or_create(
        reference=data["reference"],
        defaults={
            "business": subscription.business, "plan": subscription.plan,
            "amount": Decimal(int(data.get("amount", 0))) / 100, "currency": data.get("currency", "NGN"),
            "status": Payment.Status.SUCCESS, "paid_at": _paid_at(data), "raw": data,
        },
    )
    if created:
        _activate(subscription, subscription.plan, payment.paid_at)
    return payment


def handle_paystack_event(event):
    kind, data = event.get("event", ""), event.get("data") or {}
    if kind == "charge.success":
        reference = data.get("reference", "")
        if Payment.objects.filter(reference=reference).exists():
            return confirm_payment(reference, data)
        return _record_renewal(data)
    if kind == "subscription.create":
        customer_code = (data.get("customer") or {}).get("customer_code", "")
        Subscription.objects.filter(paystack_customer_code=customer_code).exclude(paystack_customer_code="").update(
            external_id=data.get("subscription_code", ""), paystack_email_token=data.get("email_token", ""),
        )
    elif kind in {"subscription.not_renew", "subscription.disable"}:
        Subscription.objects.filter(external_id=data.get("subscription_code", "")).exclude(external_id="").update(
            cancel_at_period_end=True
        )
    elif kind == "invoice.payment_failed":
        code = (data.get("subscription") or {}).get("subscription_code", "")
        Subscription.objects.filter(external_id=code).exclude(external_id="").update(
            status=Subscription.Status.PAST_DUE
        )
    else:
        logger.info("Ignoring Paystack event %s", kind)
    return None


def cancel_subscription(business):
    """Stop renewal; the plan stays active until the end of the paid period."""
    subscription = business.subscription
    if subscription.external_id and subscription.paystack_email_token:
        paystack.disable_subscription(subscription.external_id, subscription.paystack_email_token)
    subscription.cancel_at_period_end = True
    subscription.save(update_fields=["cancel_at_period_end", "updated_at"])
    return subscription


def expire_subscriptions(now=None):
    """End trials and unpaid/cancelled periods (after a grace period). Returns the count changed."""
    now = now or timezone.now()
    grace = timedelta(days=settings.BILLING_GRACE_DAYS)
    expired_trials = Subscription.objects.filter(status=Subscription.Status.TRIALING, trial_ends_at__lt=now)
    lapsed = Subscription.objects.filter(
        status__in=[Subscription.Status.ACTIVE, Subscription.Status.PAST_DUE], current_period_end__lt=now - grace
    )
    count = expired_trials.update(status=Subscription.Status.PAST_DUE)
    count += lapsed.filter(cancel_at_period_end=True).update(status=Subscription.Status.CANCELED)
    count += lapsed.filter(cancel_at_period_end=False, status=Subscription.Status.ACTIVE).update(
        status=Subscription.Status.PAST_DUE
    )
    return count

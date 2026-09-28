from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from .models import Plan, Subscription, UsageRecord

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
    return Subscription.objects.create(business=business, plan=plan, status=Subscription.Status.TRIALING)


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

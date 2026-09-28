from datetime import timedelta

from django.db import migrations


def backfill(apps, schema_editor):
    Subscription = apps.get_model("billing", "Subscription")
    for subscription in Subscription.objects.filter(status="TRIALING", trial_ends_at__isnull=True):
        subscription.trial_ends_at = subscription.created_at + timedelta(days=14)
        subscription.save(update_fields=["trial_ends_at"])


class Migration(migrations.Migration):
    dependencies = [("billing", "0003_plan_interval_days_plan_paystack_plan_code_and_more")]
    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]

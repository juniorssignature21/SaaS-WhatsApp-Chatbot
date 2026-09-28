from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail


@shared_task(autoretry_for=(OSError,), retry_backoff=True, max_retries=3)
def send_notification_email(recipients, subject, body):
    # One email per recipient so addresses are never disclosed to each other.
    for recipient in recipients:
        send_mail(subject, body, settings.DEFAULT_FROM_EMAIL, [recipient])

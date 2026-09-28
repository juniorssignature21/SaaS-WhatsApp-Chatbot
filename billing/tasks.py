from celery import shared_task

from .services import expire_subscriptions as _expire


@shared_task
def expire_subscriptions():
    return _expire()

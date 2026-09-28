import json
import logging

from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import paystack
from .services import handle_paystack_event

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def paystack_webhook(request):
    if not paystack.valid_signature(request.body, request.headers.get("X-Paystack-Signature", "")):
        return HttpResponseForbidden("invalid signature")
    try:
        event = json.loads(request.body)
    except ValueError:
        return HttpResponse(status=400)
    try:
        handle_paystack_event(event)
    except paystack.PaystackError:
        logger.exception("Paystack event handling failed")
        return HttpResponse(status=500)  # Paystack retries
    return HttpResponse("ok")

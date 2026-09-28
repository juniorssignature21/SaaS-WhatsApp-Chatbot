import json

from django.contrib import messages
from django.shortcuts import redirect


def flatten_errors(errors, prefix=""):
    """DRF/Django error structures -> list of readable strings."""
    out = []
    if isinstance(errors, dict):
        for key, value in errors.items():
            label = "" if key in {"non_field_errors", "__all__", "detail"} else key.replace("_", " ").capitalize()
            out.extend(flatten_errors(value, label))
    elif isinstance(errors, (list, tuple)):
        for value in errors:
            out.extend(flatten_errors(value, prefix))
    else:
        out.append(f"{prefix}: {errors}" if prefix else str(errors))
    return out


def error_redirect(request, errors, to, *args):
    for error in flatten_errors(errors):
        messages.error(request, error)
    return redirect(to, *args)


def post_data(request, *fields, booleans=(), json_fields=()):
    """Pick fields from POST, converting checkboxes and JSON textareas."""
    data = {f: request.POST.get(f, "") for f in fields if f in request.POST}
    for f in booleans:
        data[f] = f in request.POST
    for f in json_fields:
        raw = request.POST.get(f, "").strip()
        if raw:
            try:
                data[f] = json.loads(raw)
            except ValueError:
                data[f] = "__invalid_json__"
        else:
            data[f] = {}
    return data

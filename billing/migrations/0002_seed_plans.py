from decimal import Decimal

from django.db import migrations

PLANS = [
    {
        "code": "starter", "name": "Starter", "price": Decimal("15000"),
        "max_whatsapp_numbers": 1, "max_team_members": 2, "max_knowledge_documents": 10,
        "monthly_conversations": 500, "monthly_ai_responses": 2000,
        "features": {"rag": True, "tools": False, "analytics": False},
    },
    {
        "code": "business", "name": "Business", "price": Decimal("50000"),
        "max_whatsapp_numbers": 3, "max_team_members": 10, "max_knowledge_documents": 100,
        "monthly_conversations": 5000, "monthly_ai_responses": 20000,
        "features": {"rag": True, "tools": True, "analytics": True},
    },
    {
        "code": "enterprise", "name": "Enterprise", "price": Decimal("0"), "is_public": False,
        "max_whatsapp_numbers": None, "max_team_members": None, "max_knowledge_documents": None,
        "monthly_conversations": None, "monthly_ai_responses": None,
        "features": {"rag": True, "tools": True, "analytics": True, "white_label": True, "api_access": True},
    },
]


def seed(apps, schema_editor):
    Plan = apps.get_model("billing", "Plan")
    for data in PLANS:
        Plan.objects.update_or_create(code=data["code"], defaults={k: v for k, v in data.items() if k != "code"})


class Migration(migrations.Migration):
    dependencies = [("billing", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]

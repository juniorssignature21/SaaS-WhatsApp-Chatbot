from .models import Customer


def get_or_create_customer(business, phone_number, name=""):
    customer, created = Customer.objects.get_or_create(
        business=business, phone_number=phone_number, defaults={"name": name}
    )
    if not created and name and not customer.name:
        customer.name = name
        customer.save(update_fields=["name", "updated_at"])
    return customer

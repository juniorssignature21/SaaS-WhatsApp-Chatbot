from django.contrib import admin

from .models import Customer


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["phone_number", "name", "business", "updated_at"]
    list_filter = ["business"]
    search_fields = ["phone_number", "name", "email"]

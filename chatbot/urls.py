from django.urls import path

from . import views

urlpatterns = [
    path("settings/", views.AIConfigurationView.as_view(), name="chatbot-settings"),
    path("templates/", views.TemplateListView.as_view(), name="chatbot-templates"),
    path("templates/apply/", views.ApplyTemplateView.as_view(), name="chatbot-apply-template"),
    path("playground/", views.PlaygroundView.as_view(), name="chatbot-playground"),
]

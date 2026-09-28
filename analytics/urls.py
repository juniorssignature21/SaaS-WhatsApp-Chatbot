from django.urls import path

from .views import OverviewView

urlpatterns = [path("overview/", OverviewView.as_view(), name="analytics-overview")]

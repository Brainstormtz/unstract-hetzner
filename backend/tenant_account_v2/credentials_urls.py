from django.urls import path
from tenant_account_v2.credentials_view import get_default_credentials, update_default_credentials

urlpatterns = [
    path("", get_default_credentials, name="get_default_credentials"),
    path("update/", update_default_credentials, name="update_default_credentials"),
]
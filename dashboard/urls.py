from django.urls import path

from .views import auth, inbox, manage, workspace

app_name = "dashboard"

urlpatterns = [
    # Authentication
    path("login/", auth.login_view, name="login"),
    path("login/verify/", auth.login_mfa_view, name="login_mfa"),
    path("signup/", auth.signup_view, name="signup"),
    path("logout/", auth.logout_view, name="logout"),
    path("verify-email/<str:token>/", auth.verify_email_view, name="verify_email"),
    path("password-reset/", auth.password_reset_view, name="password_reset"),
    path("password-reset/<str:uidb64>/<str:token>/", auth.password_reset_confirm_view,
         name="password_reset_confirm"),
    # Overview and inbox
    path("", inbox.overview, name="overview"),
    path("inbox/", inbox.inbox, name="inbox"),
    path("inbox/new/", inbox.new_conversation, name="new_conversation"),
    path("inbox/<int:pk>/", inbox.conversation, name="conversation"),
    path("inbox/<int:pk>/poll/", inbox.conversation_poll, name="conversation_poll"),
    path("inbox/<int:pk>/<slug:action>/", inbox.conversation_action, name="conversation_action"),
    path("media/<int:pk>/", inbox.message_media, name="message_media"),
    path("customers/", inbox.customers, name="customers"),
    path("customers/<int:pk>/", inbox.customer, name="customer"),
    # Workspace
    path("whatsapp/", workspace.whatsapp, name="whatsapp"),
    path("whatsapp/<int:pk>/<slug:action>/", workspace.whatsapp_action, name="whatsapp_action"),
    path("assistant/", workspace.bot, name="bot"),
    path("assistant/template/<slug:key>/", workspace.bot_template, name="bot_template"),
    path("assistant/playground/", workspace.bot_playground, name="bot_playground"),
    path("knowledge/", workspace.knowledge, name="knowledge"),
    path("knowledge/<int:pk>/<slug:action>/", workspace.knowledge_action, name="knowledge_action"),
    path("tools/", workspace.tools, name="tools"),
    path("tools/new/", workspace.tool_form, name="tool_new"),
    path("tools/<int:pk>/", workspace.tool_form, name="tool_edit"),
    path("tools/<int:pk>/<slug:action>/", workspace.tool_action, name="tool_action"),
    # Management
    path("businesses/new/", manage.create_business_view, name="create_business"),
    path("businesses/<int:pk>/switch/", manage.switch_business, name="switch_business"),
    path("team/", manage.team, name="team"),
    path("team/invite/", manage.team_invite, name="team_invite"),
    path("team/<int:pk>/<slug:action>/", manage.team_member, name="team_member"),
    path("billing/", manage.billing, name="billing"),
    path("billing/checkout/<slug:code>/", manage.billing_checkout, name="billing_checkout"),
    path("billing/callback/", manage.billing_callback, name="billing_callback"),
    path("billing/cancel/", manage.billing_cancel, name="billing_cancel"),
    path("settings/", manage.business_settings, name="settings"),
    path("settings/api-keys/", manage.api_key_create, name="api_key_create"),
    path("settings/api-keys/<int:pk>/revoke/", manage.api_key_revoke, name="api_key_revoke"),
    path("account/", manage.account, name="account"),
    path("account/two-factor/", manage.mfa_setup, name="mfa_setup"),
    path("audit/", manage.audit_log, name="audit"),
    path("notifications/", manage.notifications, name="notifications"),
    path("notifications/<int:pk>/", manage.notification_open, name="notification_open"),
]

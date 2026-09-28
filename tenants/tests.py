from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from common.testing import add_member, api_client, make_business, make_user, make_whatsapp_account
from conversations.models import Conversation
from conversations.services import get_active_conversation, record_inbound
from customers.services import get_or_create_customer
from tenants.models import AuditLog, Membership, Role


class SignupTests(TestCase):
    def test_signup_creates_business_owner_and_defaults(self):
        response = APIClient().post("/api/v1/auth/signup/", {
            "email": "Owner@Example.com", "password": "S3cure-pass-123", "business_name": "Mama Put",
        }, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.data["business"]["slug"], "mama-put")
        membership = Membership.objects.get(user__email="owner@example.com")
        self.assertEqual(membership.role, Role.OWNER)
        self.assertTrue(hasattr(membership.business, "ai_config"))
        self.assertEqual(membership.business.subscription.plan.code, "starter")

        login = APIClient().post("/api/v1/auth/login/", {
            "email": "owner@example.com", "password": "S3cure-pass-123"}, format="json")
        self.assertEqual(login.status_code, 200)
        self.assertEqual(login.data["token"], response.data["token"])


class TenantIsolationTests(TestCase):
    def setUp(self):
        self.biz_a, self.owner_a = make_business("A")
        self.biz_b, self.owner_b = make_business("B")
        for business in (self.biz_a, self.biz_b):
            customer = get_or_create_customer(business, "2348000000001", f"cust-{business.name}")
            record_inbound(get_active_conversation(business, customer), "hello")

    def test_lists_only_own_tenant_data(self):
        client = api_client(self.owner_a)
        customers = client.get("/api/v1/customers/").data["results"]
        self.assertEqual([c["name"] for c in customers], ["cust-A"])
        conversations = client.get("/api/v1/conversations/").data["results"]
        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0]["customer"]["name"], "cust-A")

    def test_cannot_select_foreign_business(self):
        client = api_client(self.owner_a, business=self.biz_b)
        self.assertEqual(client.get("/api/v1/customers/").status_code, 404)

    def test_cannot_access_foreign_objects_by_id(self):
        foreign = Conversation.objects.get(business=self.biz_b)
        client = api_client(self.owner_a)
        self.assertEqual(client.get(f"/api/v1/conversations/{foreign.id}/").status_code, 404)
        with mock.patch("whatsapp.tasks.WhatsAppClient.send_text"):
            reply = client.post(f"/api/v1/conversations/{foreign.id}/reply/", {"content": "hi"}, format="json")
        self.assertEqual(reply.status_code, 404)

    def test_whatsapp_token_never_returned(self):
        make_whatsapp_account(self.biz_a)
        data = api_client(self.owner_a).get("/api/v1/whatsapp/accounts/").data["results"][0]
        self.assertNotIn("access_token", data)
        self.assertTrue(data["has_access_token"])

    def test_multi_business_user_must_choose(self):
        add_member(self.biz_b, Role.AGENT, user=self.owner_a)
        self.assertEqual(api_client(self.owner_a).get("/api/v1/customers/").status_code, 400)
        chosen = api_client(self.owner_a, business=self.biz_b).get("/api/v1/customers/")
        self.assertEqual([c["name"] for c in chosen.data["results"]], ["cust-B"])

    def test_suspended_business_is_blocked(self):
        self.biz_a.status = "SUSPENDED"
        self.biz_a.save()
        self.assertEqual(api_client(self.owner_a).get("/api/v1/customers/").status_code, 403)


class RoleTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Shop")
        customer = get_or_create_customer(self.business, "234800")
        account = make_whatsapp_account(self.business)
        self.conversation = get_active_conversation(self.business, customer, whatsapp_account=account)

    def test_viewer_is_read_only(self):
        viewer = api_client(add_member(self.business, Role.VIEWER))
        self.assertEqual(viewer.get("/api/v1/conversations/").status_code, 200)
        self.assertEqual(viewer.post(f"/api/v1/conversations/{self.conversation.id}/takeover/").status_code, 403)
        self.assertEqual(viewer.patch("/api/v1/chatbot/settings/", {"name": "X"}, format="json").status_code, 403)

    def test_agent_can_reply_but_not_configure(self):
        agent_user = add_member(self.business, Role.AGENT)
        agent = api_client(agent_user)
        with mock.patch("whatsapp.tasks.WhatsAppClient.send_text", return_value="wamid.x") as send:
            with self.captureOnCommitCallbacks(execute=True):
                response = agent.post(f"/api/v1/conversations/{self.conversation.id}/reply/",
                                      {"content": "Hi, Sam here"}, format="json")
        self.assertEqual(response.status_code, 201)
        send.assert_called_once_with("234800", "Hi, Sam here")
        self.conversation.refresh_from_db()
        self.assertEqual(self.conversation.status, Conversation.Status.HUMAN_HANDLING)
        self.assertEqual(self.conversation.assigned_agent, agent_user)
        self.assertEqual(agent.patch("/api/v1/chatbot/settings/", {"name": "X"}, format="json").status_code, 403)
        self.assertEqual(agent.get("/api/v1/tools/").status_code, 403)

    def test_admin_configures_bot_and_is_audited(self):
        admin = api_client(add_member(self.business, Role.ADMIN))
        response = admin.patch("/api/v1/chatbot/settings/", {"system_prompt": "Be nice"}, format="json")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(AuditLog.objects.filter(business=self.business, action="chatbot.settings_updated").exists())
        applied = admin.post("/api/v1/chatbot/templates/apply/", {"template": "restaurant"}, format="json")
        self.assertEqual(applied.data["name"], "Foodie Assistant")

    def test_only_owner_manages_admins(self):
        admin = api_client(add_member(self.business, Role.ADMIN))
        newbie = make_user()
        invite = lambda role: admin.post("/api/v1/team/", {"email": newbie.email, "role": role}, format="json")  # noqa: E731
        self.assertEqual(invite("ADMIN").status_code, 403)
        self.assertEqual(invite("AGENT").status_code, 201)
        owner_membership = Membership.objects.get(user=self.owner)
        self.assertEqual(admin.delete(f"/api/v1/team/{owner_membership.id}/").status_code, 403)


class PlanLimitTests(TestCase):
    def test_whatsapp_number_limit(self):
        business, owner = make_business("Small", plan="starter")
        make_whatsapp_account(business)
        response = api_client(owner).post("/api/v1/whatsapp/accounts/", {
            "phone_number": "+234", "phone_number_id": "new", "business_account_id": "w",
            "access_token": "t"}, format="json")
        self.assertEqual(response.status_code, 403)

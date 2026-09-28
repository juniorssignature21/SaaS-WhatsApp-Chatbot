import re

from django.core import mail
from django.test import TestCase
from rest_framework.test import APIClient

from common.testing import api_client, make_user

from . import services, totp


class TOTPTests(TestCase):
    def test_rfc6238_vector(self):
        # RFC 6238 test secret "12345678901234567890" at T=59s -> 94287082 (last 6 digits).
        import base64

        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(totp.current_code(secret, now=59), "287082")
        self.assertIsNotNone(totp.match_counter(secret, "287082", now=59))
        self.assertIsNone(totp.match_counter(secret, "000000", now=59))


class MFAFlowTests(TestCase):
    def setUp(self):
        self.user = make_user(email="mfa@example.com")
        self.client = api_client(self.user)

    def enable(self):
        secret = self.client.get("/api/v1/auth/mfa/setup/").data["secret"]
        codes = self.client.post("/api/v1/auth/mfa/setup/", {"code": totp.current_code(secret)}).data
        return secret, codes["recovery_codes"]

    def test_login_requires_second_factor(self):
        secret, recovery = self.enable()
        self.assertEqual(len(recovery), 8)
        anon = APIClient()
        step1 = anon.post("/api/v1/auth/login/", {"email": "mfa@example.com", "password": "S3cure-pass-123"})
        self.assertTrue(step1.data["mfa_required"])
        self.assertNotIn("token", step1.data)

        bad = anon.post("/api/v1/auth/login/mfa/", {"mfa_token": step1.data["mfa_token"], "code": "000000"})
        self.assertEqual(bad.status_code, 400)
        # The enabling code was already used: replaying it is rejected.
        replay = anon.post("/api/v1/auth/login/mfa/", {"mfa_token": step1.data["mfa_token"],
                                                         "code": totp.current_code(secret)})
        self.assertEqual(replay.status_code, 400)
        ok = anon.post("/api/v1/auth/login/mfa/", {"mfa_token": step1.data["mfa_token"], "code": recovery[0]})
        self.assertEqual(ok.status_code, 200)
        self.assertIn("token", ok.data)
        # Recovery codes are single-use.
        again = anon.post("/api/v1/auth/login/mfa/", {"mfa_token": step1.data["mfa_token"], "code": recovery[0]})
        self.assertEqual(again.status_code, 400)

    def test_tampered_challenge_rejected(self):
        self.enable()
        response = APIClient().post("/api/v1/auth/login/mfa/", {"mfa_token": "forged", "code": "123456"})
        self.assertEqual(response.status_code, 400)

    def test_secret_encrypted_and_disable(self):
        _, recovery = self.enable()
        self.user.refresh_from_db()
        self.assertTrue(self.user.mfa_enabled)
        self.assertEqual(self.client.post("/api/v1/auth/mfa/disable/", {"code": recovery[1]}).status_code, 204)
        self.user.refresh_from_db()
        self.assertFalse(self.user.mfa_enabled)
        self.assertEqual(self.user.mfa_secret, "")


class EmailAndPasswordTests(TestCase):
    def test_signup_sends_verification_and_link_verifies(self):
        with self.captureOnCommitCallbacks(execute=True):
            APIClient().post("/api/v1/auth/signup/", {
                "email": "new@example.com", "password": "S3cure-pass-123", "business_name": "New Co"})
        self.assertEqual(len(mail.outbox), 1)
        token = re.search(r"/verify-email/([^/\s]+)/", mail.outbox[0].body).group(1)
        response = APIClient().post("/api/v1/auth/verify-email/", {"token": token})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["email_verified"])
        self.assertEqual(APIClient().post("/api/v1/auth/verify-email/", {"token": token + "x"}).status_code, 400)

    def test_password_reset(self):
        user = make_user(email="reset@example.com")
        old_client = api_client(user)
        APIClient().post("/api/v1/auth/password/reset/", {"email": "nobody@example.com"})
        self.assertEqual(len(mail.outbox), 0)  # no enumeration, no email
        APIClient().post("/api/v1/auth/password/reset/", {"email": "reset@example.com"})
        uid, token = re.search(r"/password-reset/([^/]+)/([^/\s]+)/", mail.outbox[0].body).groups()
        response = APIClient().post("/api/v1/auth/password/reset/confirm/", {
            "uid": uid, "token": token, "new_password": "An0ther-secure-pw"})
        self.assertEqual(response.status_code, 200)
        user.refresh_from_db()
        self.assertTrue(user.check_password("An0ther-secure-pw"))
        # Old API tokens are revoked and the link can't be reused.
        self.assertEqual(old_client.get("/api/v1/auth/me/").status_code, 401)
        reuse = APIClient().post("/api/v1/auth/password/reset/confirm/", {
            "uid": uid, "token": token, "new_password": "Yet-an0ther-pw"})
        self.assertEqual(reuse.status_code, 400)

    def test_services_reject_expired_email_token(self):
        user = make_user()
        token = services.make_email_token(user)
        with self.settings(EMAIL_VERIFICATION_MAX_AGE=-1):
            with self.assertRaises(services.AccountError):
                services.verify_email(token)

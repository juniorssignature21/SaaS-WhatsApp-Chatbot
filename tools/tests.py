from django.test import TestCase

from common.netsafety import UnsafeURLError, assert_public_url
from common.testing import api_client, make_business


class ToolApiTests(TestCase):
    def test_builtin_names_are_reserved_and_secret_rotates(self):
        business, owner = make_business()
        client = api_client(owner)
        bad = client.post("/api/v1/tools/", {"name": "handoff_to_human", "description": "x",
                                             "endpoint_url": "https://example.com"}, format="json")
        self.assertEqual(bad.status_code, 400)
        created = client.post("/api/v1/tools/", {
            "name": "check_order_status", "description": "Look up an order",
            "endpoint_url": "https://example.com/tools",
            "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}}},
        }, format="json")
        self.assertEqual(created.status_code, 201, created.content)
        rotated = client.post(f"/api/v1/tools/{created.data['id']}/rotate-secret/")
        self.assertNotEqual(rotated.data["signing_secret"], created.data["signing_secret"])


class NetSafetyTests(TestCase):
    def test_blocks_internal_addresses(self):
        for url in ["http://localhost/", "http://10.0.0.5/x", "http://169.254.169.254/latest", "ftp://example.com"]:
            with self.assertRaises(UnsafeURLError, msg=url):
                assert_public_url(url)

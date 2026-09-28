from django.test import TestCase

from common.testing import api_client, make_business

from .services import record_usage


class UsageTests(TestCase):
    def test_record_usage_accumulates(self):
        business, owner = make_business()
        record_usage(business, messages_in=2)
        record_usage(business, messages_in=3, input_tokens=100)
        usage = business.usage_records.get()
        self.assertEqual((usage.messages_in, usage.input_tokens), (5, 100))
        with self.assertRaises(ValueError):
            record_usage(business, bogus=1)

        data = api_client(owner).get("/api/v1/billing/subscription/").data
        self.assertEqual(data["usage"]["messages_in"], 5)
        overview = api_client(owner).get("/api/v1/analytics/overview/")
        self.assertEqual(overview.status_code, 200)
        self.assertEqual(overview.data["messages"]["received"], 5)

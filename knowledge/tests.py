from django.test import TestCase

from common.testing import api_client, make_business

from .chunking import chunk_text
from .models import KnowledgeChunk, KnowledgeDocument
from .retrieval import search


class ChunkingTests(TestCase):
    def test_chunks_respect_size_and_overlap(self):
        text = "\n\n".join(f"Paragraph {i}. " + "word " * 60 for i in range(20))
        chunks = chunk_text(text, size=500, overlap=100)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(len(c) <= 700 for c in chunks))
        self.assertEqual(chunk_text("   "), [])


class KnowledgeApiTests(TestCase):
    def setUp(self):
        self.business, self.owner = make_business("Hotel")
        self.client = api_client(self.owner)

    def create(self, **data):
        with self.captureOnCommitCallbacks(execute=True):
            return self.client.post("/api/v1/knowledge/documents/", data, format="json")

    def test_faq_document_is_processed_and_searchable(self):
        response = self.create(title="FAQ", source_type="FAQ", faqs=[
            {"question": "What time is check-in?", "answer": "Check-in starts at 2pm."},
            {"question": "Do you have parking?", "answer": "Yes, free parking for guests."},
        ])
        self.assertEqual(response.status_code, 201, response.content)
        document = KnowledgeDocument.objects.get(pk=response.data["id"])
        self.assertEqual(document.status, "READY")
        self.assertGreaterEqual(document.chunk_count, 1)

        results = self.client.post("/api/v1/knowledge/documents/search/", {"query": "parking"}, format="json")
        self.assertIn("parking", results.data["results"][0]["content"])

    def test_search_is_tenant_scoped(self):
        self.create(title="Secret", source_type="TEXT", raw_text="Our secret discount code is TENANTA.")
        other, _ = make_business("Other")
        self.assertEqual(search(other, "secret discount code"), [])
        self.assertEqual(len(search(self.business, "secret discount code")), 1)

    def test_disabled_documents_are_not_retrieved(self):
        response = self.create(title="Old", source_type="TEXT", raw_text="Old prices: rooms cost 10000.")
        self.client.patch(f"/api/v1/knowledge/documents/{response.data['id']}/", {"enabled": False}, format="json")
        self.assertEqual(search(self.business, "room prices"), [])

    def test_private_urls_are_rejected(self):
        response = self.create(title="Intranet", source_type="URL", source_url="http://127.0.0.1/admin")
        document = KnowledgeDocument.objects.get(pk=response.data["id"])
        self.assertEqual(document.status, "FAILED")
        self.assertIn("private", document.error)
        self.assertFalse(KnowledgeChunk.objects.exists())

    def test_rejects_unsupported_file_type(self):
        from django.core.files.uploadedfile import SimpleUploadedFile

        upload = SimpleUploadedFile("malware.exe", b"MZ...")
        response = self.client.post("/api/v1/knowledge/documents/",
                                    {"title": "x", "source_type": "FILE", "file": upload})
        self.assertEqual(response.status_code, 400)


class CrawlerTests(TestCase):
    def test_crawls_same_site_respecting_robots(self):
        from unittest import mock

        from .crawler import crawl

        pages = {
            "https://shop.example/robots.txt": ("text/plain", "User-agent: *\nDisallow: /private"),
            "https://shop.example/": ("text/html", '<h1>Home</h1><a href="/faq">FAQ</a><a href="/private/x">P</a>'
                                                   '<a href="https://other.example/">Ext</a><a href="/logo.png">L</a>'),
            "https://shop.example/faq": ("text/html", "<p>We deliver in Lagos.</p><a href='/'>Home</a>"),
        }

        def fake_fetch(url):
            if url not in pages:
                raise AssertionError(f"unexpected fetch {url}")
            content_type, body = pages[url]
            return url, mock.Mock(text=body, headers={"Content-Type": content_type})

        with mock.patch("knowledge.crawler.fetch", side_effect=fake_fetch), \
             mock.patch("knowledge.loaders.fetch", side_effect=fake_fetch):
            text = crawl("https://shop.example/", max_pages=10)
        self.assertIn("Page: https://shop.example/faq", text)
        self.assertIn("We deliver in Lagos.", text)
        self.assertNotIn("private", text.lower().split("page:")[-1])

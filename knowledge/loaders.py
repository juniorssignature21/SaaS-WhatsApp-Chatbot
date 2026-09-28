"""Extract plain text from uploaded files and web pages."""

import csv
import io
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests
from django.conf import settings

from common.netsafety import assert_public_url

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv"}


class LoaderError(Exception):
    pass


def load_file(django_file, filename):
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    django_file.open("rb")
    try:
        data = django_file.read()
    finally:
        django_file.close()
    if ext == ".pdf":
        return _load_pdf(data)
    if ext == ".docx":
        return _load_docx(data)
    if ext in {".txt", ".md"}:
        return data.decode("utf-8", errors="replace")
    if ext == ".csv":
        return _load_csv(data.decode("utf-8", errors="replace"))
    raise LoaderError(f"Unsupported file type {ext or '(none)'}.")


def _load_pdf(data):
    from pypdf import PdfReader

    try:
        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 - pypdf raises many types
        raise LoaderError(f"Could not read PDF: {exc}") from exc


def _load_docx(data):
    import docx

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise LoaderError(f"Could not read DOCX: {exc}") from exc
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.append(" | ".join(cell.text for cell in row.cells))
    return "\n".join(parts)


def _load_csv(text):
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        return ""
    header, lines = rows[0], []
    for row in rows[1:]:
        lines.append("; ".join(f"{h}: {v}" for h, v in zip(header, row, strict=False) if v))
    return "\n".join(lines)


class _TextExtractor(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header"}
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "section", "article"}

    def __init__(self):
        super().__init__()
        self.parts, self.links, self._skip_depth = [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
        if tag in self.SKIP:
            self._skip_depth += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)


USER_AGENT = "WhatsAppAISaaS-KnowledgeBot/1.0"
MAX_REDIRECTS = 3


def fetch(url):
    """GET a public URL, following a few redirects with an SSRF check on every hop."""
    for _ in range(MAX_REDIRECTS + 1):
        assert_public_url(url)
        try:
            response = requests.get(url, timeout=15, allow_redirects=False, headers={"User-Agent": USER_AGENT})
        except requests.RequestException as exc:
            raise LoaderError(f"Could not fetch URL: {exc.__class__.__name__}") from exc
        if response.status_code in {301, 302, 303, 307, 308} and response.headers.get("Location"):
            url = urljoin(url, response.headers["Location"])
            continue
        if response.status_code != 200:
            raise LoaderError(f"URL returned HTTP {response.status_code}.")
        if len(response.content) > settings.KNOWLEDGE_MAX_UPLOAD_BYTES:
            raise LoaderError("Page is too large.")
        return url, response
    raise LoaderError("Too many redirects.")


def fetch_page(url):
    """Returns (final_url, text, links). Links are absolute URLs."""
    final_url, response = fetch(url)
    if "html" not in response.headers.get("Content-Type", ""):
        return final_url, response.text, []
    parser = _TextExtractor()
    parser.feed(response.text)
    text = re.sub(r"\n\s*\n+", "\n\n", "".join(parser.parts)).strip()
    return final_url, text, [urljoin(final_url, link) for link in parser.links]


def load_url(url):
    return fetch_page(url)[1]

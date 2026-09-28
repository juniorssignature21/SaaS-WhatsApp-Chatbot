# WhatsApp AI Chatbot SaaS

A multi-tenant Django platform where many businesses each connect a WhatsApp number and get their own AI assistant. The platform manages the businesses, team members, WhatsApp numbers, AI settings, knowledge bases, conversations, tools and usage from one system.

```
WhatsApp customer ─▶ WhatsApp Cloud API ─▶ POST /webhooks/whatsapp/  (verify, store, enqueue, 200)
                                                   │
                                            Redis / Celery  (queue: ai)
                                                   │
                                         chatbot.orchestrator
                          history ─ knowledge (pgvector) ─ tools ─ Claude
                                                   │
                                           response guard
                                                   │
                                  Celery (queue: whatsapp) ─▶ WhatsApp Cloud API ─▶ customer
```

## How tenants are kept apart

- One PostgreSQL database. Every tenant-owned row has a `business_id` (shared tables, not a database per tenant).
- **The server works out the tenant. It never takes it from the client.**
  - For dashboard API calls, the tenant comes from the logged-in user's `Membership`. The optional `X-Business-ID` header can only pick one of the businesses the user already belongs to. If the user isn't a member, the API returns 404, so it never reveals whether another business exists.
  - For webhooks, the tenant comes from the `phone_number_id` in the WhatsApp payload. Each number belongs to exactly one business.
- Every API view extends `tenants.mixins.TenantMixin` or `TenantModelViewSet`. These always filter by `self.business` and save with `business=self.business`.
- Each team member has one role: `OWNER > ADMIN > AGENT > VIEWER`. Views set a minimum role for reads, writes and individual actions.
- The same customer phone number counts as a separate `Customer` in each business.

The tests in `tenants/tests.py` check all of this, including cross-tenant access by ID.

## Apps

| App | Responsibility |
|---|---|
| `accounts` | Email-based `User`, signup (creates the first business), login/logout with a token, `me` |
| `tenants` | `Business`, `Membership` and roles, tenant resolution, permissions, team management, `AuditLog` |
| `whatsapp` | `WhatsAppAccount` (access token encrypted at rest), webhook (signature check, message and status handling), Graph API client, send and mark-as-read tasks |
| `customers` | End customers of each business (separate from SaaS users) |
| `conversations` | `Conversation` and `Message`, conversation lifecycle, human handoff, return to AI, agent replies, sending through the right channel |
| `chatbot` | `AIConfiguration` for each business, templates, prompts, memory, the LLM provider layer, the orchestrator and tool loop, Celery task |
| `knowledge` | Documents (PDF, DOCX, TXT, MD, CSV, URL, FAQ, pasted text), text extraction, chunking, embeddings, pgvector search |
| `tools` | Built-in tools (handoff, customer profile), plus HTTP tools each business defines, called with a signed request |
| `billing` | `Plan`, `Subscription`, monthly `UsageRecord` counters, plan limits and feature gates |
| `analytics` | Dashboard overview (messages, AI vs human replies, escalations, tokens, average first-response time) |

## Message processing

`chatbot/orchestrator.py`:

1. **Webhook** (`whatsapp/webhooks.py`):
   - Checks `X-Hub-Signature-256`.
   - Finds the number, then the business, then the customer, then the active conversation.
   - Saves the message. Retries are safe because it deduplicates on `wamid`.
   - Queues `process_incoming_message` and returns 200 right away.
2. **Celery task** (`chatbot/tasks.py`): takes a lock for the conversation, so only one AI turn runs at a time in each conversation.
3. **Checks before replying.** The bot does not reply if:
   - the business is suspended
   - the AI is turned off
   - a human is handling the conversation
   - a newer customer message is waiting. Bursts are debounced: the bot sends one reply that covers all of them.
   - the message has already been answered

   If the monthly AI quota is used up, the conversation is handed to a human instead.
4. **Build the request:**
   - The recent conversation history. Human agent replies are marked so the model knows a colleague sent them.
   - Relevant knowledge chunks, attached to the latest customer message.
   - The tools available to this business.
5. **LLM ↔ tool loop.** Runs up to `CHATBOT_MAX_TOOL_ITERATIONS` rounds. Each tool call is stored as an internal `TOOL` message so there is an audit trail.
6. **Response guard:**
   - An empty reply is replaced with the fallback message.
   - A refusal also gets the fallback message.
   - Replies are cut to WhatsApp's 4096-character limit.
   - If a human took over while the model was working, nothing is sent.
7. **Save and send.** The reply is saved as an `ASSISTANT` message and sent by the `whatsapp` queue task. Delivery statuses (sent, delivered, read) come back through the webhook and never move a message's status backwards.
8. **Usage.** Messages, AI responses, tokens (including cache reads) and tool calls are added to the month's `UsageRecord`.

If the LLM fails, transient errors are retried with backoff. If it still fails, the customer gets the fallback message and the conversation goes to a human.

### LLM defaults

`chatbot/llm.py` uses the official `anthropic` Python SDK.

- **Default model:** `claude-opus-5`. Each business can change it in its settings.
- **Adaptive thinking** is on, with an optional per-business `effort` setting (low, medium or high). For short WhatsApp replies, `low` or `medium` is usually enough and cuts latency and cost.
- **Prompt caching:** the system prompt only holds content that rarely changes for a business, so it is cached across turns. Knowledge retrieved for each turn goes into the user message instead.
- **Refusal fallbacks:** on `claude-opus-5` and `claude-fable-5-1`, server-side refusal fallbacks are turned on (`fallbacks="default"`).
- **No `temperature` setting.** Current Claude models reject sampling parameters, so the per-business `temperature` from the original design was left out. Use `effort` and the prompt to tune behaviour.
- **Other providers** can be added by implementing `LLMProvider`.
- **Offline mode:** `CHATBOT_LLM_PROVIDER=fake` uses an echo provider that makes no network calls, for development and tests.

## Tools

Built-in tools:
- `handoff_to_human` (when handoff is enabled)
- `get_customer_profile`
- `update_customer_profile`

Businesses on a plan that includes the `tools` feature can add their own tools at `/api/v1/tools/`, for example `check_order_status`, `book_appointment` or `verify_payment`. When the AI calls one, the platform sends this request to the business's endpoint:

```
POST <endpoint_url>
X-Tool-Timestamp: 1760000000
X-Tool-Signature: sha256=HMAC_SHA256(signing_secret, "<timestamp>." + body)

{"tool": "check_order_status", "input": {"order_id": "1045"},
 "context": {"business_id": 1, "conversation_id": 7,
             "customer": {"phone_number": "234...", "name": "Ada", "external_id": ""}}}
```

The response body goes back to the model as the tool result. Error codes 4xx and 5xx are reported to the model as tool errors.

Protections on tool endpoints:
- URLs that resolve to private, loopback or link-local addresses are blocked.
- Redirects are not followed.
- The signing secret is encrypted at rest and can be rotated.

## Quick start (Docker)

```bash
cp .env.example .env              # set DJANGO_SECRET_KEY, FIELD_ENCRYPTION_KEYS, WHATSAPP_*, ANTHROPIC_API_KEY
docker compose up --build
docker compose exec web python manage.py createsuperuser
```

This starts:
- `web`: Gunicorn, which runs migrations on start
- `worker`: the `ai`, `whatsapp` and default queues
- `knowledge-worker`: document processing, kept separate so it never slows down replies
- `db`: PostgreSQL 16 with pgvector
- `redis`

### Connecting WhatsApp

1. In the Meta app dashboard, set the webhook URL to `https://<your-domain>/webhooks/whatsapp/` and the verify token to `WHATSAPP_VERIFY_TOKEN`.
2. Subscribe the webhook to the `messages` field. Set `WHATSAPP_APP_SECRET` to the app secret.
3. Each business connects its number with this call:

   ```
   POST /api/v1/whatsapp/accounts/
   {"phone_number": "+234...", "phone_number_id": "...", "business_account_id": "...", "access_token": "..."}
   ```

   Then `POST /api/v1/whatsapp/accounts/{id}/verify/` checks the credentials.

## API (all under `/api/v1/`, `Authorization: Token <key>`)

| | |
|---|---|
| `auth/signup/`, `auth/login/`, `auth/logout/`, `auth/me/` | Accounts |
| `businesses/` (list/create), `business/` (current, GET/PATCH), `team/`, `audit-logs/` | Tenants |
| `whatsapp/accounts/` (+ `{id}/verify/`) | Numbers |
| `chatbot/settings/`, `chatbot/templates/`, `chatbot/templates/apply/` | Bot configuration and templates (customer support, sales, restaurant, hotel, school, real estate, ecommerce, appointments, lead generation) |
| `conversations/?status=HUMAN_HANDLING`, `conversations/{id}/messages/`, `…/reply/`, `…/takeover/`, `…/return-to-ai/`, `…/resolve/`, `…/assign/` | Inbox and human handoff |
| `customers/` | Customers |
| `knowledge/documents/` (JSON or multipart), `…/{id}/reprocess/`, `knowledge/documents/search/` | Knowledge base |
| `tools/` (+ `{id}/rotate-secret/`) | Business tools |
| `billing/plans/`, `billing/subscription/`, `billing/usage/` | Plans and usage |
| `analytics/overview/` | Dashboard numbers |

## Development

```bash
pip install -r requirements-dev.txt
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test           # SQLite
DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test  # PostgreSQL + pgvector
ruff check .
```

CI (`.github/workflows/ci.yml`) runs lint, a migration check, and the test suite on both databases.

## Security checklist

What's in place:
- **Tenant isolation:** enforced in the query and service layer, not only in the frontend.
- **Roles:** role-based access control on every endpoint.
- **Encryption at rest:** WhatsApp tokens and tool signing secrets are encrypted with Fernet (`FIELD_ENCRYPTION_KEYS`; putting a new key first rotates keys).
- **Secrets are never returned:** the API doesn't send them back, and the Django admin excludes them.
- **Webhook authentication:**
  - incoming webhooks are checked against the HMAC signature
  - verify-token comparisons are constant-time
  - outgoing tool calls are signed
- **Rate limiting:** DRF throttling, with a stricter limit on login and signup.
- **Uploads and URLs:**
  - file uploads are checked by type and size
  - uploaded files are stored under a random path inside the tenant's folder
  - URLs a business supplies are checked against SSRF
- **Audit log:** covers settings changes, numbers, team, tools and knowledge.
- **Production settings:** they refuse to start without a secret key, encryption keys or the app secret. HTTPS, HSTS and secure cookies are turned on.

## Roadmap (phases from the design)

| Phase | Status |
|---|---|
| **1. MVP:** registration, connect WhatsApp, configure the bot, receive messages, AI replies, history, dashboard API | Done (API only; no frontend in this repo yet) |
| **2.** Knowledge base / RAG, human handoff, team members, analytics | Done. Website crawling fetches a single page for now |
| **3.** Tools and business integrations | HTTP tool framework done. Next: prebuilt CRM, payment and calendar connectors |
| **4.** Billing, usage metering, several numbers | Plans, limits and metering done. Next: payment provider integration (e.g. Paystack or Flutterwave), invoices, white-labeling, public API keys |

Other next steps:
- WhatsApp message templates for replies outside the 24-hour customer-service window. Free-form replies outside the window currently fail with error `131047`, which is recorded on the message.
- Transcribing voice notes and reading images.
- Real-time dashboard updates over websockets, connected to the `conversations.signals.handoff_requested` signal.
- Email verification and MFA.
- An HNSW index on embeddings, once the embedding dimension is fixed in production.
- Replacing the `hashing` embedder with `voyage` (or another provider) for semantic search quality.

Plan prices in `billing/migrations/0002_seed_plans.py` are placeholders. Set real ones in the admin.

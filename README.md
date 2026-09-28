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
| `accounts` | Email-based `User`, signup (creates the first business), token login, email verification, password reset, two-factor authentication (TOTP with recovery codes) |
| `tenants` | `Business` (with branding), `Membership` and roles, tenant resolution, permissions, team management, API keys, `AuditLog` |
| `whatsapp` | `WhatsAppAccount` (access token encrypted at rest), webhook (signature check, message and status handling), Graph API client, message templates, media download, send and mark-as-read tasks |
| `customers` | End customers of each business (separate from SaaS users) |
| `conversations` | `Conversation` and `Message`, conversation lifecycle, human handoff, return to AI, agent replies, the 24-hour window, templates, auto-resolve, sending through the right channel |
| `chatbot` | `AIConfiguration` for each business, templates, prompts, memory, images/PDFs/voice notes, the LLM provider layer, the orchestrator and tool loop, the playground, Celery task |
| `knowledge` | Documents (PDF, DOCX, TXT, MD, CSV, FAQ, pasted text, web pages or whole small sites), text extraction, chunking, embeddings, pgvector search |
| `tools` | Built-in tools (handoff, customer profile), plus HTTP tools each business defines, called with a signed request |
| `billing` | `Plan`, `Subscription`, trials, Paystack payments and renewals, monthly `UsageRecord` counters, plan limits and feature gates |
| `analytics` | Dashboard overview (messages, AI vs human replies, escalations, tokens, average first-response time) |
| `notifications` | In-app and email alerts when a customer needs a human |
| `dashboard` | The web app for business teams (server-rendered, at `/app/`) |

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

## Web dashboard

Business teams use the dashboard at `/app/`. It is server-rendered Django (no separate frontend build), works on phones, and uses the same services and tenant rules as the API.

| Page | What it does |
|---|---|
| Sign up, sign in, two-factor, password reset, email verification | Accounts. Login is rate-limited. Two-factor uses any authenticator app, with 8 single-use recovery codes. |
| Overview | This month's numbers, a setup checklist, recent conversations, plan usage |
| Inbox | Conversations by status (active, needs human, AI, mine, resolved), search, a WhatsApp-style thread that updates live, reply, take over, return to AI, resolve, assign, send templates, message a new customer |
| Customers | Profiles, notes, CRM ID, conversation history |
| Assistant | Persona, instructions, behaviour, model and effort, template gallery |
| Playground | Chat with the bot as a customer without WhatsApp (tool calls are shown) |
| Knowledge | Upload files, import a site, write FAQs, paste text, enable/disable, test search |
| Tools | Define HTTP tools, see and rotate signing secrets |
| WhatsApp | Connect, verify, disable or disconnect numbers, rotate tokens, sync templates, webhook instructions |
| Team | Add members, change roles, remove |
| Billing | Plans, Paystack checkout, cancel renewal, usage, payment history |
| Settings & API | Business details, branding (name and colour), API keys |
| Audit log, Notifications, My account | Security history, handoff alerts, profile, password, email alerts, two-factor |

Viewers see read-only pages; agents can work the inbox; admins configure; only owners pay or manage admins.

## WhatsApp details

- **24-hour window.** WhatsApp only allows free-form messages within 24 hours of the customer's last message. After that, agent replies are refused with a clear message (HTTP 409 `service_window_closed` in the API) and the inbox offers approved templates instead. AI replies always answer a fresh customer message, so they are always inside the window.
- **Templates.** Create them in WhatsApp Manager, then sync (also every 6 hours automatically). Approved templates with body variables (`{{1}}`, `{{2}}`…) can be sent from a conversation or used to message a new customer first. Templates with header variables or media headers are shown but not sendable yet.
- **Media.** Images, documents, voice notes and videos are downloaded from Meta and stored privately (only signed-in members of that business can open them).
  - Images (JPEG, PNG, GIF, WebP up to 5 MB) and PDFs (up to 20 MB) are passed to Claude, so the bot can read a photo of a receipt or a PDF invoice.
  - Voice notes are transcribed if `TRANSCRIPTION_PROVIDER=whisper_http` is set (any OpenAI-compatible `/audio/transcriptions` endpoint, hosted or self-hosted). Otherwise the bot politely asks the customer to type.

## Scheduled jobs (Celery beat)

| Job | Schedule |
|---|---|
| Resolve AI conversations idle for `CONVERSATION_AUTO_RESOLVE_HOURS` (default 24) | every 15 min |
| End expired trials and unpaid or cancelled periods (after `BILLING_GRACE_DAYS`) | hourly |
| Sync WhatsApp templates | every 6 hours |

## Billing (Paystack)

1. Create matching plans in the Paystack dashboard and put each `PLN_…` code on the plan in the Django admin (optional: without it, payments are one-off per period).
2. Set `PAYSTACK_SECRET_KEY` and point the Paystack webhook at `https://<domain>/webhooks/paystack/`.
3. Owners pick a plan under Billing and pay on Paystack's hosted page.

How it's processed:
- The callback and the `charge.success` webhook both verify the payment. Each payment applies once, and the amount and currency must match the plan.
- Renewals extend the paid period. Failed renewals mark the subscription past due, and cancelling stops renewal at the end of the period.
- New businesses get a `TRIAL_DAYS` trial on Starter. When a trial or subscription lapses, the bot pauses and new chats go to the team.

## API keys

On plans with `api_access` (Enterprise by default), admins create keys under Settings & API. Send them as `Authorization: Api-Key wak_…`.

- Each key has a role (admin, agent or viewer) and only ever sees its own business.
- Only a hash is stored, and keys can be revoked.
- Keys can't manage other keys or list the user's businesses.
- Actions taken with a key are marked with its prefix in the audit log.

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

Open `http://localhost:8000/app/signup/` to create the first business.

This starts:
- `web`: Gunicorn, which runs migrations on start and also serves the dashboard and its static files
- `worker`: the `ai`, `whatsapp` and default queues
- `knowledge-worker`: document processing, kept separate so it never slows down replies
- `beat`: the scheduled jobs
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

## API (all under `/api/v1/`, `Authorization: Token <key>` or `Api-Key <key>`)

| | |
|---|---|
| `auth/signup/`, `auth/login/` (+ `login/mfa/`), `auth/logout/`, `auth/me/`, `auth/verify-email/` (+ `resend/`), `auth/password/reset/` (+ `confirm/`), `auth/password/change/`, `auth/mfa/setup/`, `auth/mfa/disable/` | Accounts and security |
| `businesses/` (list/create), `business/` (current, GET/PATCH), `team/`, `api-keys/`, `audit-logs/` | Tenants |
| `whatsapp/accounts/` (+ `{id}/verify/`, `{id}/sync-templates/`), `whatsapp/templates/` | Numbers and templates |
| `chatbot/settings/`, `chatbot/templates/`, `chatbot/templates/apply/`, `chatbot/playground/` | Bot configuration and templates (customer support, sales, restaurant, hotel, school, real estate, ecommerce, appointments, lead generation) |
| `conversations/?status=HUMAN_HANDLING`, `conversations/start/`, `conversations/{id}/messages/`, `…/reply/`, `…/send-template/`, `…/takeover/`, `…/return-to-ai/`, `…/resolve/`, `…/assign/`, `message-media/{id}/` | Inbox, templates, attachments and human handoff |
| `customers/` | Customers |
| `knowledge/documents/` (JSON or multipart), `…/{id}/reprocess/`, `knowledge/documents/search/` | Knowledge base |
| `tools/` (+ `{id}/rotate-secret/`) | Business tools |
| `billing/plans/`, `billing/subscription/`, `billing/usage/`, `billing/checkout/`, `billing/verify/`, `billing/cancel/`, `billing/payments/` | Plans, payments and usage |
| `analytics/overview/` | Dashboard numbers |
| `notifications/` (+ `{id}/read/`, `read-all/`) | Handoff alerts |

## Development

```bash
pip install -r requirements-dev.txt
DJANGO_SETTINGS_MODULE=config.settings.test python manage.py test           # SQLite
DJANGO_SETTINGS_MODULE=config.settings.test_postgres python manage.py test  # PostgreSQL + pgvector
ruff check .
```

To run it locally without WhatsApp or an Anthropic key (needs PostgreSQL and Redis running):

```bash
export DJANGO_SETTINGS_MODULE=config.settings.development CHATBOT_LLM_PROVIDER=fake CELERY_TASK_ALWAYS_EAGER=true
export FIELD_ENCRYPTION_KEYS=$(python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
python manage.py migrate && python manage.py runserver   # then open http://localhost:8000/app/signup/
```

Emails are printed to the console in development.

CI (`.github/workflows/ci.yml`) runs lint, a migration check, and the test suite on both databases.

## Security checklist

What's in place:
- **Tenant isolation:** enforced in the query and service layer for the API, the dashboard and API keys, not only in the UI. Tests cover access across tenants by ID.
- **Roles:** role-based access control on every endpoint and dashboard page.
- **Account security:**
  - email verification (required before connecting a WhatsApp number)
  - password reset without revealing which emails have accounts
  - two-factor authentication with replay protection and single-use recovery codes
  - login rate limiting and lockout
  - API tokens revoked when a password is reset
- **Encryption at rest:** WhatsApp tokens, tool signing secrets and 2FA secrets are encrypted with Fernet (`FIELD_ENCRYPTION_KEYS`; putting a new key first rotates keys). API keys are stored only as hashes.
- **Secrets are never returned:** the API doesn't send them back, and the Django admin excludes them.
- **Webhook authentication:**
  - WhatsApp webhooks are checked against the HMAC-SHA256 signature
  - Paystack webhooks are checked against the HMAC-SHA512 signature
  - verify-token comparisons are constant-time
  - outgoing tool calls are signed
- **Payments:** amount and currency are checked, and each payment is applied only once.
- **Rate limiting:** DRF throttling, with stricter limits on auth and the playground.
- **Uploads, URLs and media:**
  - file uploads are checked by type and size
  - uploaded files and customer media are stored under random paths in the tenant's folder and only served to that tenant's signed-in members
  - URLs a business supplies (tools and website import, including every redirect hop) are checked against SSRF
- **Audit log:** covers settings, numbers, team, tools, knowledge and API keys.
- **Production settings:** they refuse to start without a secret key, encryption keys or the app secret. HTTPS, HSTS and secure cookies are turned on, and all dashboard forms are CSRF-protected.

## Status against the design

| Phase | Status |
|---|---|
| **1. MVP:** registration, connect WhatsApp, configure the bot, receive messages, AI replies, history, dashboard | Done |
| **2.** Knowledge base / RAG, website import, human handoff, team members, analytics | Done |
| **3.** Tools, integrations, automations | HTTP tool framework, API keys and scheduled jobs done |
| **4.** Billing, usage metering, several numbers, white-labeling, API access | Done (Paystack) |

Possible next steps:
- Prebuilt connectors (e.g. Shopify, Google Calendar, Paystack payment links) on top of the tool framework.
- Templates with media or header variables, and broadcast campaigns.
- Agents sending attachments.
- Websocket updates instead of polling in the inbox.
- Invitations by email for people without an account.
- An HNSW index on embeddings once the embedding dimension is fixed in production.
- Switching to `KNOWLEDGE_EMBEDDING_PROVIDER=voyage` for better semantic search.

Plan prices in `billing/migrations/0002_seed_plans.py` are placeholders. Set real ones in the admin.

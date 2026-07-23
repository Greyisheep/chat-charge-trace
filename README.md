# Oja Connect

The demo repo for **"Chat, Charge, Trace: Instrumenting an Agentic Checkout Live"** at API Conf Lagos 2026 (July 24-25).

Oja Connect is a small Lagos market stall you shop by talking. A Gemini agent (Google ADK 2.5) answers over an AG-UI SSE stream, quotes delivery to anywhere on earth, and runs a real checkout graph that charges real (sandbox) money through Monnify. The point of the repo is not the shop; it is the surface area. Every seam an observability workshop could want is here: an LLM agent turn, tool calls, a deterministic workflow graph with fan-out and fan-in, an external payment API, a webhook receiver, and a Postgres store.

## Architecture

```
  Browser (http://localhost:5173)
  |  React 18 SPA: chat panel, product grid, Monnify inline checkout popup,
  |  mic button (Web Speech API)
  |
  |  same-origin /v1, /api, /webhooks        (VITE_API_BASE_URL empty)
  v
  nginx (docker) or Vite dev server (local dev, talks to :8000 directly)
  |
  |  POST /v1/agents/stream/   <-- AG-UI protocol over SSE
  v
  FastAPI backend (:8000)
  |
  +-- shop agent (LlmAgent, Gemini) ....... browsing, quoting, chit-chat
  |     +-- flight search sub-agent ....... mode="single_turn", grounded
  |                                         google_search, used for express
  |                                         delivery quotes while browsing
  |
  +-- checkout Workflow graph (ADK 2.5) ... the money path, no LLM trust:
  |     START -> validate_product -> geocode_destination
  |       route "standard" -> standard_quote
  |       route "express"  -> (express_base_quote, flight_fare_lookup)
  |                            -> fee_join -> compute_fee
  |       -> create_order -> payment_event
  |
  +-- Monnify sandbox client ............. init transaction, verify by
  |                                        reference (the trust boundary)
  +-- POST /webhooks/monnify ............. HMAC-SHA512 signature check,
  |                                        then RE-VERIFY with Monnify;
  |                                        the webhook nudges, never asserts
  v
  Postgres 16 (orders + ADK session store)
```

Two patterns worth noticing before the workshop:

- **The graph never trusts a model-provided number.** The checkout Workflow re-validates the product, re-geocodes the destination, and re-derives every fee itself. The flight fare comes from the search sub-agent running as a child node, wrapped in a timeout and a fallback (3x standard fee), so its failure can only ever mean "no fare", never a dead checkout.
- **Authenticate, then re-verify.** The Monnify webhook is rejected unless its `monnify-signature` header matches an HMAC-SHA512 of the raw body keyed by the secret. Even then it does not mark anything paid; it triggers the same `verify()` call against Monnify that every other path uses. Only the provider's answer moves an order.

## Prerequisites

For the one-command path:

- Docker (Compose v2)

For local dev without Docker:

- Python 3.13
- Node 22
- Docker anyway, for Postgres (or your own Postgres on 5433)

Either way you need two sets of credentials, both free:

- **Monnify sandbox account**: sign up at https://app.monnify.com, switch the dashboard to sandbox mode, and copy the API key (starts with `MK_TEST_`), secret key, and contract code.
- **Gemini API key**: create one at https://aistudio.google.com/apikey.

## Quickstart (one command)

```bash
cp .env.example .env
# open .env and fill in the Monnify sandbox keys and the Gemini key
docker compose up --build
```

Then open http://localhost:5173. Compose brings up three containers in order: Postgres (with a healthcheck), the backend on :8000 (waits for Postgres, has its own healthcheck on /api/products), and the frontend on :5173 (waits for a healthy backend).

The backend refuses to boot unless `MONNIFY_BASE_URL` contains `sandbox`. That is on purpose; this demo never talks to production Monnify and there is no override flag.

## Environment variables

Everything loads from the single `.env` at the repo root. `.env.example` is the template.

| Variable | Used by | What it is |
| --- | --- | --- |
| `MONNIFY_API_KEY` | backend | Monnify sandbox API key (`MK_TEST_...`). Authenticates the backend to Monnify. |
| `MONNIFY_SECRET_KEY` | backend | Monnify sandbox secret. Used for API auth and for checking webhook signatures. Never exposed to the browser; keep it out of anything `VITE_`. |
| `MONNIFY_CONTRACT_CODE` | backend | The sandbox contract code transactions are initialized under. |
| `MONNIFY_BASE_URL` | backend | `https://sandbox.monnify.com`. Must contain `sandbox` or the backend refuses startup. |
| `GOOGLE_API_KEY` | backend | Gemini API key for the ADK agent. |
| `GOOGLE_MODEL_NAME` | backend | Gemini model id. Default `gemini-flash-latest`. |
| `DATABASE_URL` | backend | Postgres URL. The `.env` value points at `localhost:5433` for local dev; inside docker, compose overrides it to the `postgres` service hostname, so you do not need to change it. |
| `VITE_API_BASE_URL` | frontend (build time) | Where the browser sends API calls. `http://localhost:8000` talks to the backend directly (the local dev default). Leave it **empty** to use same-origin URLs; in the docker image nginx proxies `/v1`, `/api`, and `/webhooks` to the backend container. |
| `VITE_MONNIFY_API_KEY` | frontend (build time) | The same public `MK_TEST_...` key, for the inline checkout popup. Public by design. |
| `VITE_MONNIFY_CONTRACT_CODE` | frontend (build time) | Contract code for the checkout popup. Public by design. |

One Vite subtlety: `VITE_*` values are inlined into the JS bundle **at build time**, not read at runtime. The compose file passes them to the frontend image as build args, so after changing them you need `docker compose up --build`, not just a restart.

## The demo script

This is roughly the arc shown on stage:

1. **Browse.** Ask the chat "what do you sell?". The agent calls the products tool and the answer renders as product cards (six items: Ankara Tote Bag, Adire Shirt, Suya Spice Box, Beaded Bracelet, Jollof Spice Mix, Woven Raffia Hat).
2. **Quote.** Ask "how much to deliver the suya spice box to Nairobi, express?". The agent geocodes the destination, and for express it consults the flight search sub-agent for a live fare before pricing.
3. **Buy.** Say "I'll take it" and give a name and email when asked. The checkout Workflow graph runs: validate, geocode, price, create the order, initialize a Monnify sandbox transaction. The payment modal opens with the Monnify inline checkout.
4. **Pay.** In the sandbox popup, pay by bank transfer (the sandbox gives you a test account to "send" to and completes on its own) or use Monnify's sandbox test card. No real money exists anywhere in this flow.
5. **Verify.** When the popup completes, the frontend calls `/api/orders/{reference}/verify`; the backend asks Monnify for the truth and only then marks the order paid. The webhook receiver does the same dance if Monnify calls in first. The chat closes the loop with a thank-you and the order status.

## Local dev without Docker

The pre-docker workflow still works and is nicer for hacking:

```bash
# 1. Postgres only (publishes 5433 on localhost)
docker compose up -d postgres

# 2. Backend
cd backend
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
./run.sh                      # uvicorn main:app --reload --port 8000

# 3. Frontend (separate terminal)
cd frontend
npm install
npm run dev                   # Vite dev server on 5173
```

Keep `VITE_API_BASE_URL=http://localhost:8000` in `.env` for this path; the Vite dev server reads the repo-root `.env` directly (its `envDir` points at the repo root) and the browser talks to the backend on :8000, which allows the :5173 origin via CORS.

## Voice input

The mic button in the chat composer uses the browser's Web Speech API for speech-to-text (and speechSynthesis for read-aloud). This works in Chrome-family browsers (Chrome, Edge, Arc); Firefox and some others do not implement SpeechRecognition, and there the button simply does not appear. No audio is sent to this backend; the browser's own speech service does the transcription.

## Troubleshooting

- **Port already in use (5433, 8000, 5173).** Something else owns the port. Find it with `lsof -i :8000` and stop it, or edit the left side of the port mapping in `docker-compose.yml`.
- **Backend exits immediately with a sandbox error.** `MONNIFY_BASE_URL` does not contain `sandbox`. Set it back to `https://sandbox.monnify.com`; there is no override.
- **Checkout popup opens then errors, or transactions fail to initialize.** Monnify keys are wrong or from the wrong mode. All three values must come from the **sandbox** view of the Monnify dashboard, and `VITE_MONNIFY_API_KEY` / `VITE_MONNIFY_CONTRACT_CODE` must match `MONNIFY_API_KEY` / `MONNIFY_CONTRACT_CODE`. Remember the rebuild: `docker compose up --build`.
- **Agent replies with a model error.** Check `GOOGLE_API_KEY`, and that `GOOGLE_MODEL_NAME` is a model your key can use. `gemini-flash-latest` is the safe default; a typo here surfaces as a 404 from the Gemini API in the backend logs (`docker compose logs backend`).
- **Chat streams nothing through :5173 but works on :8000 directly.** You are on an old frontend image from before the nginx proxy config. `docker compose build frontend && docker compose up -d frontend`.
- **Postgres in a weird state / want a clean slate.** `docker compose down -v` removes the `oja_pgdata` volume. Orders and chat sessions are gone; the schema is recreated automatically on the next backend boot (no migrations, by design).
- **Frontend shows products but chat fails.** Products come from a plain REST endpoint; chat needs the Gemini key. Almost always a `GOOGLE_API_KEY` problem.

## Role in the workshop

This repo is the raw material for the workshop, not the finished product. `main` ships deliberately **uninstrumented**: `backend/app/telemetry.py` is a no-op seam (`traced()` yields, `register_secret()` does nothing), and every interesting call site in the codebase already routes through it. During the session we fill that seam live with OpenTelemetry (spans for the agent turn, each tool, each checkout graph node, the Monnify client calls, and the webhook verify), point it at a Jaeger container, and then read a buy-storm stress test through the traces. See issue #7 for the plan; a completed branch serves as the answer key.

So if you are reading this before the workshop: run the demo, buy a suya spice box, and notice how little you can see about what just happened. That is the point we start from.

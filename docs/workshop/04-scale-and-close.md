# Stage 4: Scale and close (5 min, both)

## Goal

Answer the "does this survive production" question with a few credible,
specific points, then restate the thesis and send the room home with the repo.

## Pre-flight

- Nothing to drive. This is talking over the last two or three slides.
- Have `AGENTIC_OBSERVABILITY.md` open in case someone wants the deep version.

## Script

### 1. Scale, the honest gotchas (3 min)

Pick two or three of these, do not list all of them:

- **Content is the cost.** A metadata-only span is a few hundred bytes; one
  carrying a full prompt plus history is tens to hundreds of kilobytes, 50 to
  300 times bigger. So we keep bodies OFF the trace store (Tempo) and send them
  to Loki and, optionally, Langfuse. This is also why Tempo truncates at 2048
  bytes: the spec itself says do not put bodies on spans in production.

- **Agents break the sampling playbook.** Tail sampling's default decision
  window is 30 seconds. A multi-minute agent trace gets a sampling decision
  made on partial data, so a "keep the slow ones" policy systematically DROPS
  the slow agent traces it was meant to catch. The fix exists (span-ingest
  strategy, or deciding after the root span), but it is niche knowledge. Great
  "your assumptions do not hold for agents" beat.

- **PII for a payments app.** Buyer content carries names, emails, and account
  numbers. We redact at the collector, on the branch that keeps content, before
  it ever reaches a store or the cloud. The trace store never sees it because we
  strip bodies off that branch entirely.

- **The resumability trap.** ADK can re-run a tool "at least once, possibly more
  than once" on resume. For a Monnify disbursement that is a double-payment risk.
  We do not use resume today; if we did, every money-moving tool would need an
  idempotency key first. Name it as a thing you have to design for.

### 2. One command, one repo (1 min)

- `git clone`, `docker compose up --build`, and the audience has the entire
  thing: the agent, the checkout, and the full observability stack, on one
  network. Everything you saw is self-hostable and in the repo. Langfuse is the
  only cloud piece and it is optional.

### 3. Close on the thesis (1 min)

- "An agentic system that moves real money is not observable by default. A 200
  and a latency number do not tell you whether the agent looped, what it cost,
  or why it chose what it chose. The good news is the framework already computes
  most of it. You have to be intentional: turn it on, keep the signals the
  cookbook throws away, and put the numbers where you can watch them. Do that,
  and you can finally answer WHY."

## Key points

- Content off spans; bodies to Loki/Langfuse; redact at the collector.
- Tail sampling defaults betray long agent traces.
- Resume plus money needs idempotency.
- One command, one repo, self-hostable.

## The aha moment

The clone-and-go line. The room realizes the whole talk is a repo they can run
before they leave the building.

## Pointers for the curious (drop in chat or on a slide)

- `AGENTIC_OBSERVABILITY.md`: the full operator and talk companion.
- Issues #4, #6, #10, #11 on the repo: the decision records for the cart, voice,
  pairings, and observability, with the why behind each choice.
- `OTEL.md`: the tracing-layer reference.

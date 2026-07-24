# Chat, Charge, Trace: workshop run-of-show

Presenter guide for the API Conf Lagos 2026 workshop. One markdown per stage,
in order. Read this page first, then run each stage doc top to bottom.

Talk thesis: **an agentic system that moves real money can loop, re-plan, and
burn tokens while your APM reports 200 OK. You have to instrument it
intentionally to answer WHY it did what it did.** The demo is a Lagos market
shop agent (Oja Connect) that checks out through the real Monnify sandbox, and
we watch it from the outside.

## Stages

| # | File | Who | Time | One line |
|---|---|---|---|---|
| 0 | [00-hook.md](00-hook.md) | Claret | 2 min | A live purchase. "This agent moves real money." |
| 1 | [01-the-agentic-system.md](01-the-agentic-system.md) | Claret | 15 min | How it is built. Agents are graphs. Two doors. |
| 2 | [02-basic-tracing.md](02-basic-tracing.md) | Kruse | 15 min | Turn on OTel and Grafana. What ran, and how long. |
| 3 | [03-agentic-tracing.md](03-agentic-tracing.md) | Claret | 20 min | The payoff: cache, cost, re-planning, decisions. |
| 4 | [04-scale-and-close.md](04-scale-and-close.md) | Both | 5 min | Scale, PII, one-command, the thesis restated. |

**Glance-at-during-the-talk:** [CHEATSHEET.md](CHEATSHEET.md), one page of
commands, URLs, the exact demo drives, panels, and TraceQL.

Total about 57 minutes, leaving room to breathe in a 60 minute slot.

## Before the room (pre-flight, do this once)

From the repo root:

```bash
cp .env.example .env      # then fill in the real Monnify + Gemini keys
docker compose up --build -d
```

That brings up the whole thing on one network:

| URL | What |
|---|---|
| http://localhost:5173 | The Oja Connect app (shop + chat) |
| http://localhost:3000 | Grafana (dashboard "Oja Connect: Agent Observability") |
| http://localhost:8000/api/products | Backend health (should list 9 products) |

Wait until `docker compose ps` shows every service healthy or up. Then open the
app and drive one throwaway purchase so the dashboard has data before you start.

Grafana has no login in this setup (anonymous viewer). If it asks, the demo
runs fine as the anonymous org viewer.

## The one rule for a live demo

Every stage doc has an **If it breaks** section. Read it before you present that
stage. The two things most likely to wobble on conference wifi are the Monnify
popup (external) and voice (mic plus network). Both have fallbacks below.

## What the audience takes home

The repo. Tell them at the start: `git clone`, `docker compose up --build`, and
they have the whole thing, agent, checkout, and the observability stack, to
poke at on Monday. The workshop is a guided tour of a repo they keep.

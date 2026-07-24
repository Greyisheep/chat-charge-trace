# Stage 1: The agentic system (15 min, Claret)

## Goal

Show how the thing you just watched is built, and plant the one idea the whole
talk hangs on: **an agent is a graph. Deterministic where money moves, an LLM
where language lives.** Still no observability. This is the system under test.

## Pre-flight

- App at http://localhost:5173.
- Optional: the repo open in an editor to show a file or two, but keep it light,
  this is a talk, not a code read.
- Voice: decide up front whether you are doing the voice beat (see below). If
  the room wifi is shaky, skip live voice and describe it.

## Script

### 1. The two doors (3 min)

- **Text door:** the chat you already used. Built on AG-UI, streaming the
  agent's replies, product cards, and the payment event over SSE.
- **Voice door:** click the mic ("Start live voice"). This is **Gemini Live**,
  native audio-to-audio (`gemini-3.1-flash-live-preview`). Speak a request.
- Teaching point on voice: **it is audio-native.** It understands your accent
  from the audio directly, not from a transcript. You will sometimes see the
  transcript render as gibberish while the agent still gets it exactly right,
  that is the proof it is not a speech-to-text-to-LLM pipeline. For structured
  fields like name and email you can also just type mid-conversation and it
  lands in the same voice session.

### 2. Agents are graphs (6 min)

- The agent has tools: browse products, quote delivery, manage a cart, check out.
- The interesting part is **checkout**. It is not the LLM deciding how to move
  money. It is an explicit **ADK Workflow graph**: validate the cart, geocode
  the destination, price delivery (distance based, or an express "fly it" branch
  that fans out to a live flight-fare lookup and rejoins), create the order,
  emit the payment event.
- Say it plainly: **the model chooses WHAT the buyer wants; the graph decides
  HOW the money moves.** Every charged number is derived inside the graph, so
  nothing the model hallucinates can move money.
- Money is exact Decimal to the kobo, never a float. One delivery fee per order,
  goods subtotal plus that fee, verified by re-querying Monnify, never trusted
  from the model.

### 3. Same brain, both doors (3 min)

- Text and voice share the same agent, the same tools, the same checkout graph.
- One nuance worth naming: the graph runs directly on the text door, and on the
  voice door it runs through a compatible direct path (the live runtime cannot
  host the graph engine the same way). Same steps, same money math, both doors.

### 4. Hand off (1 min)

- "So it works. It takes real money. But right now it is a black box: I can see
  the chat, I cannot see the reasoning, the cost, or the failure. Kruse is going
  to open it up."

## Key points

- An agent is a graph; put determinism where money moves.
- Two doors, one brain.
- Money is derived and verified, never trusted from the model.

## The aha moment

"The model chooses what; the graph decides how the money moves." That single
sentence reframes the checkout from "scary LLM touching payments" to
"deterministic pipeline the LLM merely triggers."

## If it breaks

- **Voice wifi or mic issues:** skip the live voice beat, describe it in one
  sentence, and lean on the text door. The voice story survives being told.
- **Do not** deep-dive the code. If someone asks for internals, point them at
  the repo (`backend/app/agent/checkout_graph.py`) and keep the room moving.

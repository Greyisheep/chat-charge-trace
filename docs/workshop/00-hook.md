# Stage 0: The hook (2 min, Claret)

## Goal

Before a single word about architecture or observability, prove the thing is
real: an AI agent that takes a Nigerian buyer from "I want that" to a verified
payment. Earn the right to spend the next hour looking inside it.

## Pre-flight

- App open at http://localhost:5173, chat panel visible.
- A clean or near-clean chat (reload the page for the empty state).
- Have the Monnify sandbox test card or the transfer flow ready in your head.
- Observability is running but you are NOT showing it yet. This stage is the
  black box.

## Script (beat by beat)

1. "This is Oja Connect, a Lagos market you talk to." Point at the product grid.
2. In the chat, type or say: **"I want the suya spice box, ship it to Lagos."**
   The agent renders a product card with a distance-priced delivery quote.
3. Confirm the buy. Give a name and email when asked. The agent creates the
   order and the **Monnify checkout popup opens right there in the chat.**
4. Complete the sandbox payment (transfer or test card). The chat shows
   **"Payment verified"** and the agent thanks the buyer by name.
5. Land the line: **"That was a real payment on the Monnify sandbox. Now, when
   this agent misbehaves in production, and it will, what do you actually see?
   For the next hour we are going to look inside it."**

Do not explain how any of it works yet. That is Stage 1.

## Key point (say it once)

This is not a chatbot demo. It is an agent wired to a real payment rail. The
stakes of "why did it do that" are money, not vibes.

## The aha moment

The Monnify popup appearing inside the conversation, then "Payment verified."
The room should feel that this is a working system, not a slide.

## If it breaks

- **Monnify popup does not open or the sandbox is slow (wifi):** you have a
  pre-recorded 20 second clip of the full purchase. Play it, say "here it is on
  a good connection," and move on. Do not fight the wifi live.
- **The agent asks for details in a loop:** just type the name and email
  plainly; it resolves. If it stalls, reload and re-drive; it is 2 minutes,
  keep it moving.
- **Do not** enter a real card. Sandbox only, test values only.

"""Flight price lookup agent (grounded search via ADK's built-in tool).

google-adk still requires google_search to live alone on a dedicated agent,
so the search is its own LlmAgent, used in two places:

  * as a mode="single_turn" sub-agent of the shop agent (2.5.0's replacement
    for direct AgentTool use): auto-wrapped as an inline tool the shop agent
    calls for browsing-stage express quotes;
  * as a graph node inside the checkout workflow, where its fare feeds the
    express fee computation (contained by a timeout and a fallback).
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.tools import google_search

from ..config import get_settings
from .telemetry_hooks import make_usage_recording_callback

FLIGHT_INSTRUCTION = """
You are a flight fare researcher. Given a destination city, use Google Search
to find the current approximate price of a one-way economy flight from Lagos,
Nigeria (LOS) to that city.

Respond with ONLY one terse JSON object, no prose and no code fences:
{"price": "<number, no separators>", "currency": "<NGN or USD>", "route": "Lagos to <city>"}

Rules:
- Prefer NGN prices from Nigerian booking sites; otherwise USD is fine.
- Pick one representative mid-range fare, not the cheapest outlier.
- If you truly cannot find any fare, respond with
  {"price": "", "currency": "", "route": "Lagos to <city>"}.
""".strip()


def create_flight_agent(mode: str | None = None) -> LlmAgent:
    """Fresh instance per use site (sub-agent and graph node must not share).

    mode="single_turn" for the shop agent's sub_agents list; None for the
    checkout graph, where build_node defaults a standalone LlmAgent to
    single_turn itself.
    """
    resolved_model = get_settings().google_model_name
    return LlmAgent(
        model=resolved_model,
        # Token/cost metrics for the fare-lookup sub-agent's own LLM calls (#11).
        after_model_callback=make_usage_recording_callback(resolved_model),
        name="FlightPriceAgent",
        description=(
            "Finds the current approximate one-way economy flight fare from "
            "Lagos to a destination city using Google Search. Use it before "
            "quoting express fly-it delivery."
        ),
        static_instruction=FLIGHT_INSTRUCTION,  # literal; cache-friendly
        tools=[google_search],
        mode=mode,
    )

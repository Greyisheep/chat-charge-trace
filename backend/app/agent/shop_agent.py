"""Build the Oja Connect shop agent (google-adk 2.5.0 LlmAgent).

2.5.0 idioms in use:
  * static_instruction: the literal, byte-stable persona and policy prefix
    (cache-friendly under the App's ContextCacheConfig).
  * instruction: a small InstructionProvider injecting only per-session facts.
  * sub_agents with mode="single_turn": the flight fare specialist is
    auto-wrapped as an inline tool (the modern replacement for AgentTool),
    running in the parent session for browsing-stage express quotes.
  * BuiltInPlanner with a bounded thinking budget, thoughts never streamed.

The checkout money path is NOT left to the model: the checkout FunctionTool
runs the explicit workflow graph in checkout_graph.py.
"""

from __future__ import annotations

from google.adk.agents import LlmAgent
from google.adk.planners import BuiltInPlanner
from google.adk.tools import FunctionTool
from google.genai import types

from ..config import get_settings
from . import tools
from .flight_agent import create_flight_agent
from .instructions import SHOP_STATIC_INSTRUCTION, shop_dynamic_instruction


def create_shop_agent(model: str | None = None) -> LlmAgent:
    """Build the shop agent.

    The optional `model` override lets the native-voice live path (run_live)
    reuse this exact same agent, tools, and instructions while pointing at a
    Gemini Live audio model instead of the text model. The SSE path calls this
    with no argument and keeps google_model_name unchanged.
    """
    return LlmAgent(
        model=model or get_settings().google_model_name,
        name="OjaConnectShopAgent",
        description=(
            "Conversational shop assistant for Oja Connect: browse products, "
            "quote delivery, run checkout, and check payment status."
        ),
        static_instruction=SHOP_STATIC_INSTRUCTION,
        instruction=shop_dynamic_instruction,
        planner=BuiltInPlanner(
            # Bounded thinking, thoughts never streamed to the buyer.
            thinking_config=types.ThinkingConfig(include_thoughts=False, thinking_budget=512)
        ),
        tools=[
            FunctionTool(func=tools.list_products),
            FunctionTool(func=tools.get_product),
            FunctionTool(func=tools.quote_delivery),
            FunctionTool(func=tools.checkout),
            FunctionTool(func=tools.check_order_status),
        ],
        sub_agents=[create_flight_agent(mode="single_turn")],
    )

"""
Deterministic Mock LLM Engine for MOCK_LLM=1 offline testing and CLI pipelines.
Zero network dependencies.
"""
from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable, Dict, List, Optional


def extract_prompt_sku(prompt: str) -> Optional[str]:
    # Look for SKUs like LAPTOP-001, PROD-001, ASUS-ROG, etc.
    m = re.search(r'\b([A-Za-z0-9]+-[A-Za-z0-9-]+)\b', prompt)
    if m:
        return m.group(1).upper()
    m2 = re.search(r'\b(PROD\d+|LAPTOP\d+)\b', prompt, re.IGNORECASE)
    if m2:
        return m2.group(1).upper()
    return None


def _call_fn(fn: Callable[..., Any], **kwargs) -> Any:
    try:
        res = fn(**kwargs)
    except TypeError:
        res = fn(kwargs)
    if hasattr(res, "__await__"):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                from concurrent.futures import ThreadPoolExecutor
                def _run():
                    nl = asyncio.new_event_loop()
                    asyncio.set_event_loop(nl)
                    try:
                        return nl.run_until_complete(res)
                    finally:
                        nl.close()
                with ThreadPoolExecutor(max_workers=1) as ex:
                    return ex.submit(_run).result()
            else:
                return loop.run_until_complete(res)
        except Exception:
            return None
    return res


class MockLLMEngine:
    """Handles deterministic chat completions and tool calls for MOCK_LLM=1."""

    @staticmethod
    def handle_chat(messages: List[Dict[str, Any]]) -> str:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        last_lower = last_user.lower()
        if "select" in last_lower or "algorithm" in last_lower or "tool" in last_lower:
            if any(w in last_lower for w in ("maximize", "profit", "greedy")):
                return json.dumps({"tool_name": "profit_maximization", "reason": "Profit maximization requested"})
            elif any(w in last_lower for w in ("volatility", "spread", "range")):
                return json.dumps({"tool_name": "volatility_adjusted", "reason": "Volatility adjusted pricing selected"})
            return json.dumps({"tool_name": "rule_based", "reason": "Deterministic rule-based competitive pricing"})

        if "title" in last_lower or "summarize" in last_lower:
            sku = extract_prompt_sku(last_user)
            if sku:
                return f"Pricing Optimization for {sku}"
            return "Pricing Discussion"

        return f"[Mock LLM] Processed request: {last_user[:50]}"

    @staticmethod
    def handle_chat_with_tools(
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        functions_map: Dict[str, Callable[..., Any]],
        trace_id: Optional[str] = None,
    ) -> tuple[str, List[str]]:
        last_user = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                last_user = m.get("content", "")
                break

        sku = extract_prompt_sku(last_user)
        target_sku = sku or "PROD-001"
        tools_used: List[str] = []

        # =========================================================================
        # Case A: PricingOptimizerAgent context (autonomous optimization workflow)
        # =========================================================================
        if "publish_price_proposal" in functions_map or "run_pricing_algorithm" in functions_map:
            our_price = 100.0
            cost = 70.0
            title = target_sku
            if "get_product_info" in functions_map:
                pinfo = _call_fn(functions_map["get_product_info"], sku=target_sku)
                tools_used.append("get_product_info")
                if isinstance(pinfo, dict) and pinfo.get("product"):
                    prod = pinfo["product"]
                    our_price = float(prod.get("current_price") or 100.0)
                    cost = float(prod.get("cost") or (our_price * 0.7))
                    title = prod.get("title") or target_sku

            if "get_market_intelligence" in functions_map:
                _call_fn(functions_map["get_market_intelligence"], product_title=title)
                tools_used.append("get_market_intelligence")

            proposed_price = round(our_price * 0.96, 2)
            margin = (proposed_price - cost) / proposed_price if proposed_price > 0 else 0.2
            if "run_pricing_algorithm" in functions_map:
                algo_res = _call_fn(
                    functions_map["run_pricing_algorithm"],
                    algorithm="rule_based",
                    sku=target_sku,
                    our_price=our_price,
                    competitor_price=round(our_price * 0.98, 2),
                    cost=cost,
                    market_records=[],
                    min_margin=0.12,
                )
                tools_used.append("run_pricing_algorithm")
                if isinstance(algo_res, dict) and "proposed_price" in algo_res:
                    proposed_price = float(algo_res["proposed_price"])
                    margin = float(algo_res.get("margin") or margin)

            if "validate_price" in functions_map:
                _call_fn(
                    functions_map["validate_price"],
                    proposed_price=proposed_price,
                    current_price=our_price,
                    cost=cost,
                    min_margin=0.12,
                )
                tools_used.append("validate_price")

            if "publish_price_proposal" in functions_map:
                _call_fn(
                    functions_map["publish_price_proposal"],
                    sku=target_sku,
                    old_price=our_price,
                    new_price=proposed_price,
                )
                tools_used.append("publish_price_proposal")

            return (
                f"### Autonomous Price Optimization for `{target_sku}`\n"
                f"- **Proposed Price:** ${proposed_price:.2f}\n"
                f"- **Current Price:** ${our_price:.2f}\n"
                f"- **Algorithm:** `rule_based`\n"
                f"- **Margin:** {margin:.1%}\n\n"
                f"Price proposal published to event bus and logged.",
                tools_used,
            )

        # =========================================================================
        # Case B: UserInteractionAgent context (chat turn)
        # =========================================================================
        last_lower = last_user.lower()
        is_pricing_intent = (
            sku is not None
            or any(w in last_lower for w in ("price", "pricing", "optimize", "proposal", "cost", "catalog", "margin"))
        )

        if is_pricing_intent:
            if "optimize_price" in functions_map:
                try:
                    functions_map["optimize_price"](sku=target_sku)
                    tools_used.append("optimize_price")
                except Exception:
                    pass

            proposals_list = []
            if "list_price_proposals" in functions_map:
                try:
                    p_res = functions_map["list_price_proposals"](sku=target_sku, limit=5)
                    tools_used.append("list_price_proposals")
                    if isinstance(p_res, dict):
                        proposals_list = p_res.get("items", [])
                except Exception:
                    pass

            if proposals_list:
                latest = proposals_list[0]
                prop_p = float(latest.get("proposed_price") or 0.0)
                curr_p = float(latest.get("current_price") or 0.0)
                algo = latest.get("algorithm", "rule_based")
                p_id = latest.get("id", "prop_1")
                margin = float(latest.get("margin") or 0.0)
                return (
                    f"### Price Optimization for SKU `{target_sku}`\n"
                    f"- **Recommended Price:** ${prop_p:.2f}\n"
                    f"- **Current Price:** ${curr_p:.2f}\n"
                    f"- **Algorithm:** `{algo}`\n"
                    f"- **Margin:** {margin:.1%}\n"
                    f"- **Proposal ID:** `{p_id}`\n\n"
                    f"Proposal generated and stored in SQLite database.",
                    tools_used,
                )
            else:
                return (
                    f"### Price Analysis for SKU `{target_sku}`\n"
                    f"Optimization executed via `optimize_price(sku='{target_sku}')`. Proposal logged.",
                    tools_used,
                )

        return (
            "[Mock LLM] I am the FluxPricer assistant running in offline mock mode. "
            "You can ask me to optimize prices for any SKU in your catalog (e.g. 'Optimize LAPTOP-001').",
            tools_used,
        )

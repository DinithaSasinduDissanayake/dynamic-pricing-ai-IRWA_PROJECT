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


def detect_algorithm(messages: List[Dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content") or ""
            # 1. Explicit "User Request: ... algorithm <algo>"
            req_match = re.search(r'User Request:\s*.*?\balgorithm\s+([a-zA-Z0-9_-]+)', content, re.IGNORECASE)
            if req_match:
                candidate = req_match.group(1).lower().replace("-", "_")
                if candidate in ("profit_maximization", "profit", "premium"):
                    return "profit_maximization"
                if candidate in ("volatility_adjusted", "volatility", "spread"):
                    return "volatility_adjusted"
                if candidate in ("rule_based", "rule"):
                    return "rule_based"

            # 2. "User Request: <text>"
            user_req_match = re.search(r'User Request:\s*([^\n]+)', content, re.IGNORECASE)
            if user_req_match:
                sub_text = user_req_match.group(1).lower()
                if re.search(r'\b(profit|profit_maximization|maximize|premium)\b', sub_text):
                    return "profit_maximization"
                if re.search(r'\b(volatility|volatility_adjusted|spread)\b', sub_text):
                    return "volatility_adjusted"
                return "rule_based"

            # 3. Direct chat prompt
            lower_content = content.lower()
            if re.search(r'\b(profit|profit_maximization|maximize|premium)\b', lower_content):
                return "profit_maximization"
            if re.search(r'\b(volatility|volatility_adjusted|spread)\b', lower_content):
                return "volatility_adjusted"
            return "rule_based"
    return "rule_based"


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
        except Exception as e:
            raise RuntimeError(f"Async tool call failed: {e}")
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
            algo = detect_algorithm(messages)
            return json.dumps({"tool_name": algo, "reason": f"Deterministic selection for {algo}"})

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
        target_sku = sku or "LAPTOP-001"
        tools_used: List[str] = []
        algo = detect_algorithm(messages)

        # =========================================================================
        # Case A: PricingOptimizerAgent context (autonomous optimization workflow)
        # =========================================================================
        if "publish_price_proposal" in functions_map or "run_pricing_algorithm" in functions_map:
            # 1. Fetch real product info
            if "get_product_info" not in functions_map:
                raise RuntimeError("PricingOptimizer workflow missing 'get_product_info' tool")

            pinfo = _call_fn(functions_map["get_product_info"], sku=target_sku)
            tools_used.append("get_product_info")
            if not isinstance(pinfo, dict) or not pinfo.get("ok"):
                err_detail = pinfo.get("error") if isinstance(pinfo, dict) else f"Unknown error ({pinfo})"
                raise RuntimeError(f"Failed to lookup product info for SKU '{target_sku}': {err_detail}")

            our_price = pinfo.get("current_price")
            cost = pinfo.get("cost")
            title = pinfo.get("title") or target_sku

            if our_price is None or cost is None:
                raise RuntimeError(f"Incomplete catalog data for SKU '{target_sku}': price={our_price}, cost={cost}")

            our_price = float(our_price)
            cost = float(cost)

            # 2. Gather market intelligence
            market_records = []
            competitor_price = None
            if "get_market_intelligence" in functions_map:
                minfo = _call_fn(functions_map["get_market_intelligence"], product_title=title)
                tools_used.append("get_market_intelligence")
                if isinstance(minfo, dict) and minfo.get("ok"):
                    competitor_price = minfo.get("competitor_price")
                    market_records = minfo.get("market_records") or []

            # 3. Execute pricing algorithm
            if "run_pricing_algorithm" not in functions_map:
                raise RuntimeError("PricingOptimizer workflow missing 'run_pricing_algorithm' tool")

            algo_res = _call_fn(
                functions_map["run_pricing_algorithm"],
                algorithm=algo,
                sku=target_sku,
                our_price=our_price,
                competitor_price=competitor_price,
                cost=cost,
                market_records=market_records,
                min_margin=0.12,
            )
            tools_used.append("run_pricing_algorithm")
            if not isinstance(algo_res, dict) or "proposed_price" not in algo_res:
                raise RuntimeError(f"Pricing algorithm '{algo}' failed for SKU '{target_sku}': {algo_res}")

            proposed_price = float(algo_res["proposed_price"])
            margin = float(algo_res.get("margin") if algo_res.get("margin") is not None else ((proposed_price - cost) / proposed_price if proposed_price > 0 else 0.0))
            algorithm_used = algo_res.get("algorithm") or algo

            # 4. Validate price
            if "validate_price" in functions_map:
                val_res = _call_fn(
                    functions_map["validate_price"],
                    proposed_price=proposed_price,
                    current_price=our_price,
                    cost=cost,
                    min_margin=0.12,
                )
                tools_used.append("validate_price")

            # 5. Publish price proposal
            if "publish_price_proposal" in functions_map:
                pub_res = _call_fn(
                    functions_map["publish_price_proposal"],
                    sku=target_sku,
                    old_price=our_price,
                    new_price=proposed_price,
                    margin=margin,
                    algorithm=algorithm_used,
                )
                tools_used.append("publish_price_proposal")

            return (
                f"### Autonomous Price Optimization for `{target_sku}`\n"
                f"- **Proposed Price:** ${proposed_price:.2f}\n"
                f"- **Current Price:** ${our_price:.2f}\n"
                f"- **Cost:** ${cost:.2f}\n"
                f"- **Algorithm:** `{algorithm_used}`\n"
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
                    functions_map["optimize_price"](sku=target_sku, algorithm=algo)
                    tools_used.append("optimize_price")
                except Exception as e:
                    raise RuntimeError(f"optimize_price failed for {target_sku}: {e}")

            # Look up recent proposals
            proposals_list = []
            if "list_price_proposals" in functions_map:
                try:
                    p_res = functions_map["list_price_proposals"](sku=target_sku, limit=5)
                    tools_used.append("list_price_proposals")
                    if isinstance(p_res, dict):
                        proposals_list = p_res.get("items", [])
                except Exception as e:
                    pass

            if proposals_list:
                latest = proposals_list[0]
                prop_p = float(latest.get("proposed_price") or 0.0)
                curr_p = float(latest.get("current_price") or 0.0)
                algo_name = latest.get("algorithm", algo)
                p_id = latest.get("id", "prop_1")
                margin = float(latest.get("margin") or 0.0)
                return (
                    f"### Price Optimization for SKU `{target_sku}`\n"
                    f"- **Recommended Price:** ${prop_p:.2f}\n"
                    f"- **Current Price:** ${curr_p:.2f}\n"
                    f"- **Algorithm:** `{algo_name}`\n"
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

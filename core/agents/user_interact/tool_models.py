"""Typed argument models for chat tools — the single source of truth.

Each Pydantic v2 model describes the arguments of one entry in
``core.agents.user_interact.tools.TOOLS_MAP``. The OpenAI tool specs in
``tool_schemas.py`` are GENERATED from these models, and dispatch-time
validation (``validate_tool_args``) runs incoming tool-call arguments
through them before the implementation is invoked — so schema and
implementation cannot drift.

Conventions:
- ``extra="forbid"`` on every model → additionalProperties: false.
- Optional fields are ``... | None`` so strict-mode schemas can mark every
  property as required with a nullable type (OpenAI strict rules); dispatch
  drops ``None`` values so implementation defaults still apply.
"""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional, Tuple, Type

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class _ToolArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListInventoryItemsArgs(_ToolArgs):
    """List items from the local product catalog (app/data.db:product_catalog). Use for inventory overviews."""

    search: Optional[str] = Field(default=None, description="Filter by substring in SKU or title.")
    limit: Optional[int] = Field(default=50, ge=1, le=200, description="Maximum number of items to return (1-200, default 50).")


class GetInventoryItemArgs(_ToolArgs):
    """Get a single inventory item by SKU from app/data.db:product_catalog."""

    sku: str = Field(description="Item SKU (exact match)")


class ListPricingListArgs(_ToolArgs):
    """List current market pricing entries from app/data.db:pricing_list."""

    search: Optional[str] = Field(default=None, description="Filter by substring in product_name.")
    limit: Optional[int] = Field(default=50, ge=1, le=200, description="Maximum number of entries to return (1-200, default 50).")


class ListPriceProposalsArgs(_ToolArgs):
    """List recent price proposals from app/data.db:price_proposals."""

    sku: Optional[str] = Field(default=None, description="Optional filter by SKU")
    limit: Optional[int] = Field(default=50, ge=1, le=200, description="Maximum number of proposals to return (1-200, default 50).")


class ListMarketDataArgs(_ToolArgs):
    """List products from data/market.db:market_data (market research data). Use this to find products by brand or name in market data."""

    search: Optional[str] = Field(default=None, description="Filter by substring in product_name or brand.")
    limit: Optional[int] = Field(default=50, ge=1, le=200, description="Maximum number of records to return (1-200, default 50).")


class OptimizePriceArgs(_ToolArgs):
    """Request autonomous price optimization for a product SKU. The Price Optimizer Agent will analyze market data, run pricing algorithms, validate constraints, and publish a price proposal."""

    sku: str = Field(description="Product SKU to optimize pricing for")
    algorithm: Optional[Literal["rule_based", "profit_maximization", "volatility_adjusted"]] = Field(
        default=None,
        description=(
            "Pricing optimization algorithm to use. Options: 'rule_based' (default), "
            "'profit_maximization' (elasticity-based), 'volatility_adjusted' (market volatility-aware)."
        ),
    )


class ApplyPriceProposalArgs(_ToolArgs):
    """Apply an approved price proposal to the live product catalog (updates product_catalog.current_price). TWO-STEP CONFIRMATION FLOW: first call with confirm=false to get a preview (sku, current vs proposed price, margin, algorithm, rationale) and show it to the user. Only after the user explicitly agrees, call again with confirm=true to apply. Applying validates ownership, rejects already-applied proposals, re-checks the 12% margin floor against live cost, records an audit row in price_history, and publishes a price.applied event. Never call with confirm=true without the user's explicit approval of the previewed change."""

    proposal_id: str = Field(description="ID of the price proposal to apply (from list_price_proposals).")
    confirm: Optional[bool] = Field(
        default=False,
        description="false = preview only; true = actually apply (requires prior user approval).",
    )


class CheckStaleMarketDataArgs(_ToolArgs):
    """Check for market data entries in data/market.db:market_data that are older than a specified threshold. Returns count and details of stale items."""

    threshold_minutes: Optional[int] = Field(default=60, ge=1, description="Age threshold in minutes. Default is 60.")


class ScanForAlertsArgs(_ToolArgs):
    """Scan for and retrieve all pricing alerts and incidents from app/alert.db:incidents. Returns open, acknowledged, and resolved alerts with severity levels and details."""


class GetPortfolioUrgencyArgs(_ToolArgs):
    """Compute portfolio-wide pricing urgency summary across all catalog products. Evaluates margin, competitor gap, market data staleness, pending proposals, and open alerts to return a compact ranked list (most urgent first). Use when asked which products most urgently need attention or price changes."""


# --- Legacy aliases in TOOLS_MAP (not exposed to the LLM via TOOL_SCHEMAS) ---


class ListInventoryArgs(_ToolArgs):
    """Legacy alias for list_inventory_items."""

    search: Optional[str] = Field(default="")
    limit: Optional[int] = Field(default=100, ge=1, le=200)


class ListMarketPricesArgs(_ToolArgs):
    """Legacy alias for list_pricing_list."""

    search: Optional[str] = Field(default="")
    limit: Optional[int] = Field(default=10, ge=1, le=200)


class ListProposalsArgs(_ToolArgs):
    """Legacy alias for list_price_proposals."""

    sku: Optional[str] = Field(default="")
    limit: Optional[int] = Field(default=10, ge=1, le=200)


class RunPricingWorkflowArgs(_ToolArgs):
    """Legacy alias for optimize_price (rule_based)."""

    sku: str = Field(description="Product SKU to optimize pricing for")


class CollectMarketDataArgs(_ToolArgs):
    """Stub: trigger market data collection."""


class RequestMarketFetchArgs(_ToolArgs):
    """Stub: request a market fetch."""


TOOL_MODELS: Dict[str, Type[BaseModel]] = {
    "list_inventory_items": ListInventoryItemsArgs,
    "get_inventory_item": GetInventoryItemArgs,
    "list_pricing_list": ListPricingListArgs,
    "list_price_proposals": ListPriceProposalsArgs,
    "list_market_data": ListMarketDataArgs,
    "optimize_price": OptimizePriceArgs,
    "apply_price_proposal": ApplyPriceProposalArgs,
    "check_stale_market_data": CheckStaleMarketDataArgs,
    "scan_for_alerts": ScanForAlertsArgs,
    "get_portfolio_urgency": GetPortfolioUrgencyArgs,
    # Legacy aliases (dispatchable but not advertised in TOOL_SCHEMAS)
    "list_inventory": ListInventoryArgs,
    "list_market_prices": ListMarketPricesArgs,
    "list_proposals": ListProposalsArgs,
    "run_pricing_workflow": RunPricingWorkflowArgs,
    "collect_market_data": CollectMarketDataArgs,
    "request_market_fetch": RequestMarketFetchArgs,
}


def _terse_errors(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return "; ".join(parts)


def _schema_hint(model: Type[BaseModel]) -> Dict[str, Any]:
    schema = model.model_json_schema()
    return {
        "properties": {
            k: {kk: vv for kk, vv in v.items() if kk in ("type", "enum", "anyOf", "description", "minimum", "maximum")}
            for k, v in (schema.get("properties") or {}).items()
        },
        "required": schema.get("required", []),
    }


def validate_tool_args(tool_name: str, args: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
    """Validate raw tool-call arguments against the tool's Pydantic model.

    Returns ``(True, cleaned_kwargs)`` on success — ``None`` values dropped so
    implementation defaults apply — or ``(False, structured_error)`` on
    validation failure (the error-as-message pattern: never raises).

    Tools without a registered model pass through unchanged.
    """
    model = TOOL_MODELS.get(tool_name)
    if model is None:
        return True, dict(args or {})
    try:
        validated = model.model_validate(args or {})
    except ValidationError as exc:
        return False, {
            "ok": False,
            "error": f"invalid arguments for {tool_name}: {_terse_errors(exc)}",
            "expected": _schema_hint(model),
        }
    return True, validated.model_dump(exclude_none=True)

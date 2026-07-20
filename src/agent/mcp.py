"""
MCP (Model Context Protocol) server — Streamable HTTP transport.

Exposes the marketplace as MCP tools so any MCP client (Claude Desktop,
Claude Code, Cursor, etc.) can browse the catalog and purchase products
autonomously. Stateless JSON-RPC 2.0 over POST /mcp.

Connect with:  claude mcp add --transport http ai-commerce https://<host>/mcp
"""
import json
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from src.database import AsyncSessionLocal

router = APIRouter(tags=["mcp"])

PROTOCOL_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
SERVER_INFO = {"name": "ai-commerce", "version": "1.0.0"}

TOOLS = [
    {
        "name": "browse_catalog",
        "description": (
            "Browse the AI Commerce product catalog. Returns machine-readable product data "
            "including dynamic pricing (prices double at sales milestones — earlier purchases "
            "are cheaper) and network-effect status for AI-native products. No auth required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Free-text search over name/description"},
                "category": {"type": "string", "description": "Filter by category (prompt, guide, workflow, agent)"},
                "max_price": {"type": "number", "description": "Maximum price in USD", "default": 50},
                "limit": {"type": "integer", "description": "Max results", "default": 20},
            },
        },
    },
    {
        "name": "get_product_details",
        "description": "Get full details for one product by its slug, including pricing model and AI-native metadata.",
        "inputSchema": {
            "type": "object",
            "properties": {"slug": {"type": "string", "description": "Product slug, e.g. 'axiom-zero'"}},
            "required": ["slug"],
        },
    },
    {
        "name": "register_agent",
        "description": (
            "Register this AI agent as a customer and receive an API key. Required once before "
            "purchasing. The api_key is returned only once — store it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "email": {"type": "string", "description": "Contact email (agent's or owner's)"},
                "name": {"type": "string", "description": "Agent name"},
                "framework": {
                    "type": "string",
                    "description": "Agent framework",
                    "enum": ["langchain", "autogpt", "crewai", "openai_assistant", "dify", "n8n", "flowise", "mastra", "custom", "unknown"],
                },
                "callback_url": {"type": "string", "description": "Optional webhook URL for content delivery"},
            },
            "required": ["email", "name"],
        },
    },
    {
        "name": "purchase_product",
        "description": (
            "Purchase a product with your API key. Order is confirmed instantly (no human "
            "approval). Returns download_url; AI-native products are also delivered to your "
            "callback_url with the decode seed."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "API key from register_agent"},
                "product_id": {"type": "integer", "description": "Product ID from browse_catalog"},
                "coupon_code": {"type": "string", "description": "Optional coupon code"},
            },
            "required": ["api_key", "product_id"],
        },
    },
    {
        "name": "get_network_status",
        "description": (
            "Get network-effect status for an AI-native product: owner count, unlocked tiers "
            "(tier 1 at 10 owners, tier 2 at 50, tier 3 at 100), current dynamic price, and "
            "when the next price doubling hits. Requires api_key."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "api_key": {"type": "string", "description": "API key from register_agent"},
                "product_id": {"type": "integer", "description": "Product ID"},
            },
            "required": ["api_key", "product_id"],
        },
    },
]


async def _call_tool(name: str, args: dict[str, Any]) -> Any:
    from src.agent.router import (
        AgentCheckoutRequest,
        AgentRegisterRequest,
        agent_catalog,
        agent_checkout,
        get_network_status,
        register_agent,
    )

    async with AsyncSessionLocal() as session:
        if name == "browse_catalog":
            return await agent_catalog(
                category=args.get("category"),
                min_price=0,
                max_price=float(args.get("max_price", 50)),
                search=args.get("search"),
                limit=int(args.get("limit", 20)),
                x_api_key=None,
                session=session,
            )

        if name == "get_product_details":
            from sqlmodel import select
            from src.agent.router import _calc_dynamic_price
            from src.products.models import Product, ProductStatus
            result = await session.execute(
                select(Product).where(Product.slug == args["slug"], Product.status == ProductStatus.ACTIVE)
            )
            p = result.scalar_one_or_none()
            if not p:
                raise HTTPException(404, f"Product '{args['slug']}' not found")
            return {
                "id": p.id,
                "slug": p.slug,
                "name": p.name,
                "description": p.description,
                "category": p.category,
                "price_usd": _calc_dynamic_price(p),
                "pricing_model": p.pricing_model,
                "content_format": p.content_format,
                "network_value_enabled": p.network_value_enabled,
                "sales_count": p.sales_count,
                "tags": p.tags.split(",") if p.tags else [],
            }

        if name == "register_agent":
            data = AgentRegisterRequest(
                email=args["email"],
                name=args["name"],
                framework=args.get("framework", "unknown"),
                callback_url=args.get("callback_url"),
            )
            resp = await register_agent(data=data, session=session)
            return resp.model_dump()

        if name == "purchase_product":
            data = AgentCheckoutRequest(
                product_id=int(args["product_id"]),
                coupon_code=args.get("coupon_code"),
            )
            resp = await agent_checkout(data=data, x_api_key=args["api_key"], session=session)
            return resp.model_dump()

        if name == "get_network_status":
            return await get_network_status(
                product_id=int(args["product_id"]),
                x_api_key=args["api_key"],
                session=session,
            )

    raise HTTPException(404, f"Unknown tool: {name}")


def _rpc_result(req_id: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_error(req_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


async def _handle_rpc(msg: dict) -> Optional[dict]:
    """Handle one JSON-RPC message. Returns None for notifications."""
    method = msg.get("method", "")
    req_id = msg.get("id")
    params = msg.get("params") or {}

    if req_id is None:
        return None  # notification (e.g. notifications/initialized) — no response

    if method == "initialize":
        client_version = params.get("protocolVersion", "")
        version = client_version if client_version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return _rpc_result(req_id, {
            "protocolVersion": version,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
            "instructions": (
                "AI Commerce — the first marketplace where AIs buy from AIs. "
                "Flow: browse_catalog → register_agent (once, store the api_key) → purchase_product. "
                "AI-native products use dynamic pricing: buying earlier is cheaper."
            ),
        })

    if method == "ping":
        return _rpc_result(req_id, {})

    if method == "tools/list":
        return _rpc_result(req_id, {"tools": TOOLS})

    if method == "resources/list":
        return _rpc_result(req_id, {"resources": []})

    if method == "prompts/list":
        return _rpc_result(req_id, {"prompts": []})

    if method == "tools/call":
        tool_name = params.get("name", "")
        tool_args = params.get("arguments") or {}
        try:
            result = await _call_tool(tool_name, tool_args)
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, default=str)}],
                "isError": False,
            })
        except HTTPException as e:
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": f"Error {e.status_code}: {e.detail}"}],
                "isError": True,
            })
        except Exception as e:
            return _rpc_result(req_id, {
                "content": [{"type": "text", "text": f"Error: {e}"}],
                "isError": True,
            })

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


@router.post("/mcp")
async def mcp_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_rpc_error(None, -32700, "Parse error"), status_code=400)

    if isinstance(body, list):  # batch
        responses = [r for m in body if isinstance(m, dict) and (r := await _handle_rpc(m))]
        if not responses:
            return Response(status_code=202)
        return JSONResponse(responses)

    response = await _handle_rpc(body)
    if response is None:
        return Response(status_code=202)
    return JSONResponse(response)


@router.get("/mcp")
async def mcp_get():
    # SSE streaming not offered — stateless JSON responses only (spec-compliant signal)
    return Response(status_code=405, headers={"Allow": "POST"})

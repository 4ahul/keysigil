from __future__ import annotations

import asyncio
import logging
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from keysigil.core.engine import KeyForge

server = Server("keysigil")

_TOOLS: list[Tool] = [
    Tool(
        name="create_api_key",
        description="Create a new API key. Returns the plaintext key — save it, shown once.",
        inputSchema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Human-readable name for this key"},
                "prefix": {"type": "string", "description": "Key prefix, e.g. kf_live or kf_test"},
                "expires_days": {"type": "integer", "description": "Expiry in days (optional)"},
                "rate_requests": {"type": "integer", "description": "Max requests per window"},
                "rate_window": {"type": "string", "description": "Rate window e.g. 1m, 1h (default 1m)"},
                "monthly_tokens": {"type": "integer", "description": "Monthly token budget"},
                "permissions": {"type": "array", "items": {"type": "string"}, "description": "Permission strings"},
                "db_url": {"type": "string", "description": "Database URL (default sqlite:///keyforge.db)"},
            },
            "required": ["name"],
        },
    ),
    Tool(
        name="verify_api_key",
        description="Verify an API key. Returns validity, permissions, remaining rate/budget.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "The API key to verify"},
                "db_url": {"type": "string"},
            },
            "required": ["key"],
        },
    ),
    Tool(
        name="list_api_keys",
        description="List all API keys.",
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Filter by prefix"},
                "db_url": {"type": "string"},
            },
        },
    ),
    Tool(
        name="revoke_api_key",
        description="Revoke an API key immediately.",
        inputSchema={
            "type": "object",
            "properties": {
                "key_id": {"type": "string"},
                "db_url": {"type": "string"},
            },
            "required": ["key_id"],
        },
    ),
    Tool(
        name="track_token_usage",
        description="Record LLM token consumption against a key's budget.",
        inputSchema={
            "type": "object",
            "properties": {
                "key_id": {"type": "string"},
                "input_tokens": {"type": "integer"},
                "output_tokens": {"type": "integer"},
                "model": {"type": "string"},
                "db_url": {"type": "string"},
            },
            "required": ["key_id"],
        },
    ),
    Tool(
        name="get_usage_stats",
        description="Get token usage statistics for a key.",
        inputSchema={
            "type": "object",
            "properties": {
                "key_id": {"type": "string"},
                "db_url": {"type": "string"},
            },
            "required": ["key_id"],
        },
    ),
]


def _kf(args: dict[str, Any]) -> KeyForge:
    return KeyForge(args.get("db_url", "sqlite:///keyforge.db"))


@server.list_tools()
async def list_tools() -> list[Tool]:
    return _TOOLS


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        text = await _dispatch(name, arguments)
    except Exception as e:
        text = f"Error: {e}"
    return [TextContent(type="text", text=text)]


async def _dispatch(name: str, args: dict[str, Any]) -> str:
    if name == "create_api_key":
        return await _handle_create(args)
    if name == "verify_api_key":
        return await _handle_verify(args)
    if name == "list_api_keys":
        return await _handle_list(args)
    if name == "revoke_api_key":
        return await _handle_revoke(args)
    if name == "track_token_usage":
        return await _handle_track(args)
    if name == "get_usage_stats":
        return await _handle_usage(args)
    raise ValueError(f"Unknown tool: {name}")


async def _handle_create(args: dict[str, Any]) -> str:
    from datetime import timedelta
    kf = _kf(args)
    await kf.setup()
    rl = {"requests": args["rate_requests"], "window": args.get("rate_window", "1m")} if args.get("rate_requests") else None
    tb = {"monthly": args["monthly_tokens"]} if args.get("monthly_tokens") else None
    result = await kf.create_key(
        name=args["name"],
        prefix=args.get("prefix"),
        expires_in=timedelta(days=args["expires_days"]) if args.get("expires_days") else None,
        rate_limit=rl,
        token_budget=tb,
        permissions=args.get("permissions", []),
    )
    return f"Created key:\nID: {result.key.id}\nName: {result.key.name}\nKey: {result.plaintext}\n⚠ Save this key — shown once."


async def _handle_verify(args: dict[str, Any]) -> str:
    kf = _kf(args)
    await kf.setup()
    result = await kf.verify(args["key"])
    if result.valid:
        lines = [f"VALID: {result.key_name} ({result.key_id})"]
        if result.permissions:
            lines.append(f"Permissions: {', '.join(result.permissions)}")
        if result.rate_limit_remaining is not None:
            lines.append(f"Rate limit remaining: {result.rate_limit_remaining}")
        if result.token_budget_remaining is not None:
            lines.append(f"Token budget remaining: {result.token_budget_remaining:,}")
        return "\n".join(lines)
    return f"INVALID: {result.error}"


async def _handle_list(args: dict[str, Any]) -> str:
    kf = _kf(args)
    await kf.setup()
    keys = await kf.list_keys(args.get("prefix"))
    if not keys:
        return "No keys found."
    lines = [f"{'ID':<20} {'Name':<20} {'Status':<10} {'Prefix'}"]
    lines.append("-" * 60)
    for k in keys:
        lines.append(f"{k.id:<20} {k.name:<20} {k.status.value:<10} {k.prefix}")
    return "\n".join(lines)


async def _handle_revoke(args: dict[str, Any]) -> str:
    kf = _kf(args)
    await kf.setup()
    await kf.revoke_key(args["key_id"])
    return f"Revoked: {args['key_id']}"


async def _handle_track(args: dict[str, Any]) -> str:
    kf = _kf(args)
    await kf.setup()
    await kf.track_usage(
        key_id=args["key_id"],
        input_tokens=args.get("input_tokens", 0),
        output_tokens=args.get("output_tokens", 0),
        model=args.get("model"),
    )
    total = args.get("input_tokens", 0) + args.get("output_tokens", 0)
    return f"Recorded {total:,} tokens for {args['key_id']}"


async def _handle_usage(args: dict[str, Any]) -> str:
    kf = _kf(args)
    await kf.setup()
    stats = await kf.get_usage(args["key_id"])
    lines = [
        f"Usage for {stats.key_id}",
        f"Total: {stats.total_tokens:,} tokens",
        f"Input: {stats.input_tokens:,} / Output: {stats.output_tokens:,}",
        f"Records: {stats.record_count}",
    ]
    if stats.by_model:
        lines.append("By model: " + ", ".join(f"{m}: {t:,}" for m, t in stats.by_model.items()))
    return "\n".join(lines)


async def _run_server() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def run(*, host: str = "localhost", port: int = 8080) -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(_run_server())


if __name__ == "__main__":
    run()

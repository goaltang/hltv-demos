"""Permission-aware stdio MCP adapter for WorkBuddy and other MCP clients."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import (
    _build_download_plan,
    _execute_download_plan,
    _public_download_plan,
    discover_csgo,
    doctor,
)

_PLAN_TTL_SECONDS = 10 * 60
_MAX_PENDING_PLANS = 32
_PLANS: dict[str, dict[str, Any]] = {}
_PLAN_LOCK = asyncio.Lock()

mcp = FastMCP(
    "hltv-demos",
    instructions=(
        "Plan first. Show the exact plan and approval token to the user. Never call "
        "execute_approved_plan until the user explicitly approves that plan. Keep the MCP "
        "host's interactive command/network/file approval enabled."
    ),
)


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _prune_plans() -> None:
    now = time.monotonic()
    for key in list(_PLANS):
        if _PLANS[key]["expires"] <= now:
            del _PLANS[key]
    while len(_PLANS) >= _MAX_PENDING_PLANS:
        oldest = min(_PLANS, key=lambda key: _PLANS[key]["created"])
        del _PLANS[oldest]


def _configured_download_dir() -> str:
    return os.path.realpath(os.path.expanduser(
        os.environ.get("HLTV_DEMOS_DL_DIR") or "~/Downloads"
    ))


@mcp.tool(
    description="Read-only environment checks. This tool does not download, install, or modify files.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False),
)
def check_environment() -> dict:
    return doctor()


@mcp.tool(
    description=(
        "Resolve an exact, read-only HLTV download plan. Show the complete result and approval "
        "token to the user. The token expires in 10 minutes and must not be used without explicit "
        "human approval."
    ),
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True),
)
async def plan_download(
    event: str,
    maps: str = "",
    latest: int = 0,
    keep_rars: bool = True,
) -> dict:
    if not event or len(event) > 500 or len(maps) > 500:
        return {"ready": False, "error": "event/maps input is empty or too long"}
    if latest < 0 or latest > 100:
        return {"ready": False, "error": "latest must be between 0 and 100"}
    if not maps and latest == 0:
        return {"ready": False, "error": "set maps or latest; unbounded event downloads are refused"}
    environment = doctor()
    if not environment.get("ok"):
        return {"ready": False, "environment": environment,
                "error": "environment checks failed; fix them before planning execution"}

    try:
        prepared = await asyncio.to_thread(
            _build_download_plan,
            event, maps, latest, keep_rars, "", "", None, False,
        )
    except (ValueError, RuntimeError) as exc:
        return {"ready": False, "error": str(exc)}
    public = _public_download_plan(prepared)
    if public.get("error") or public.get("errors"):
        return {"ready": False, "plan": public, "error": "fix plan errors before approval"}
    if any(not item.get("size") for item in prepared["plan"]):
        return {"ready": False, "plan": public, "error": "all archive sizes must be known"}
    try:
        max_bytes = int(os.environ.get("HLTV_DEMOS_MCP_MAX_BYTES", "50000000000"))
        if max_bytes <= 0:
            raise ValueError
    except ValueError:
        return {"ready": False, "plan": public,
                "error": "HLTV_DEMOS_MCP_MAX_BYTES must be a positive integer"}
    if public["total_bytes"] > max_bytes:
        return {"ready": False, "plan": public,
                "error": f"plan exceeds configured byte limit ({max_bytes})"}

    prepared["resolved_csgo"] = os.path.realpath(discover_csgo())
    prepared["resolved_download"] = _configured_download_dir()
    public = _public_download_plan(prepared)
    fingerprint = hashlib.sha256(json.dumps(
        public, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")).hexdigest()
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    async with _PLAN_LOCK:
        _prune_plans()
        _PLANS[_hash_token(token)] = {
            "created": now,
            "expires": now + _PLAN_TTL_SECONDS,
            "fingerprint": fingerprint,
            "prepared": prepared,
            "state": "pending",
        }
    return {
        "ready": True,
        "approval_token": token,
        "plan_fingerprint": fingerprint,
        "expires_in_minutes": 10,
        "plan": public,
        "next_step": (
            "Show this exact plan, fingerprint, destinations, retention setting, and token to the "
            "user. Call execute_approved_plan only after explicit approval."
        ),
    }


@mcp.tool(
    description=(
        "Execute exactly one frozen plan. This writes archives and CS2 demo files. Call only after "
        "the user explicitly approves the displayed plan and supplies its one-use token."
    ),
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=True
    ),
)
async def execute_approved_plan(approval_token: str) -> dict:
    key = _hash_token(approval_token)
    async with _PLAN_LOCK:
        _prune_plans()
        record = _PLANS.get(key)
        if not record or record["state"] != "pending":
            return {"ok": False, "error": "invalid, expired, or already consumed approval token"}
        record["state"] = "in_progress"
        prepared = record["prepared"]
        fingerprint = record["fingerprint"]
        del _PLANS[key]  # Consume before I/O so retries and parallel calls cannot duplicate work.
    result = await asyncio.to_thread(_execute_download_plan, prepared, False, None)
    return {
        "ok": not bool(result.get("error") or result.get("errors")),
        "plan_fingerprint": fingerprint,
        "result": result,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()

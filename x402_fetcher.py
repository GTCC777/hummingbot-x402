"""x402_fetcher — minimal async helper that GETs a URL and transparently pays an x402
HTTP 402 challenge (USDC on Base or any EVM network the endpoint accepts).

Deliberately free of any Hummingbot imports so it can be unit-tested standalone and
reused outside the data feed. Uses the official `x402` SDK (pip install "x402[evm,httpx]").

SPDX-License-Identifier: Apache-2.0
"""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Optional

import httpx
from eth_account import Account
from x402 import x402Client
from x402.http.clients.httpx import x402HttpxClient
from x402.mechanisms.evm import EthAccountSigner
from x402.mechanisms.evm.exact import ExactEvmScheme

# One USDC = 10**6 atomic units; x402 amounts are atomic strings.
USDC_DECIMALS = 6


def build_paying_client(private_key: str, max_price_usdc: Optional[Decimal] = None) -> httpx.AsyncClient:
    """Return an httpx.AsyncClient that auto-pays x402 402 challenges with the given key.

    max_price_usdc, when set, refuses any challenge above that amount — a per-call budget
    guard so a bot can never be surprised by a repriced endpoint.
    """
    signer = EthAccountSigner(Account.from_key(private_key))
    client = x402Client()

    if max_price_usdc is not None:
        cap_atomic = int(max_price_usdc * (10 ** USDC_DECIMALS))

        def _cap_policy(version, accepts):  # refuse any option above the cap; keep the rest
            allowed = [
                a for a in accepts
                if int(getattr(a, "amount", None) or getattr(a, "max_amount_required", 0) or 0) <= cap_atomic
            ]
            if not allowed:
                raise ValueError(
                    f"x402 challenge exceeds max_price_usdc={max_price_usdc}: "
                    f"cheapest option is above the configured cap"
                )
            return allowed

        client.register_policy(_cap_policy)

    client.register("eip155:*", ExactEvmScheme(signer))
    return x402HttpxClient(client, follow_redirects=True, timeout=15.0)


def extract_json_path(payload: Any, path: str) -> Decimal:
    """Extract a Decimal from a JSON payload with a dotted path, e.g.:

        "markets.0.mark_price"      -> payload["markets"][0]["mark_price"]
        "greeks.price"              -> payload["greeks"]["price"]
        ""                          -> payload itself (bare-number APIs)

    Raises ValueError with a helpful message when the path is missing or non-numeric —
    a wrong price silently defaulting to 0 is how market-making bots lose money.
    """
    node = payload
    if path:
        for part in path.split("."):
            if isinstance(node, list):
                try:
                    node = node[int(part)]
                except (ValueError, IndexError) as exc:
                    raise ValueError(f"json_path segment '{part}' invalid for a list of length {len(node)}") from exc
            elif isinstance(node, dict):
                if part not in node:
                    raise ValueError(f"json_path segment '{part}' not found; available keys: {list(node)[:12]}")
                node = node[part]
            else:
                raise ValueError(f"json_path segment '{part}' cannot descend into {type(node).__name__}")
    if isinstance(node, bool) or not isinstance(node, (int, float, str)):
        raise ValueError(f"json_path resolved to non-numeric {type(node).__name__}: {node!r}")
    value = Decimal(str(node))
    if value.is_nan():
        raise ValueError("json_path resolved to NaN")
    return value


async def fetch_paid_value(client: httpx.AsyncClient, url: str, json_path: str = "") -> Decimal:
    """GET the URL (paying a 402 if challenged) and return the numeric value at json_path.

    The response may be bare text ("1786.9") or JSON; json_path selects within JSON.
    """
    resp = await client.get(url)
    text = resp.text
    if resp.status_code != 200:
        raise RuntimeError(f"x402 fetch failed: HTTP {resp.status_code}: {text[:200]}")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return Decimal(text.strip())
    return extract_json_path(payload, json_path)

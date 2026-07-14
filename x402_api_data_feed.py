"""X402APIDataFeed — a Hummingbot data feed that pays x402 micropayments per poll.

Drop-in sibling of Hummingbot's stock CustomAPIDataFeed (hummingbot/data_feed/
custom_api_data_feed.py, Apache-2.0), extended with:

  1. Automatic HTTP 402 handling — signs a USDC payment (Base or any EVM network the
     endpoint accepts) with the `x402` SDK and retries, so any machine-payable API
     (e.g. the PulseNetwork catalog: funding rates, options greeks, macro series,
     FDIC/BLS/USGS primitives) becomes a native Hummingbot price/signal source.
  2. JSON-path extraction — paid APIs return JSON, not a bare number; `json_path`
     selects the value, e.g. "markets.0.mark_price" or "greeks.price".
  3. A per-call budget cap (`max_price_usdc`) so a repriced endpoint can never
     silently overspend your wallet.
  4. A 402-aware health check — for a paid endpoint, "402 Payment Required" means
     ALIVE (the stock feed would mark it down).

Usage inside a script strategy:

    from x402_api_data_feed import X402APIDataFeed

    feed = X402APIDataFeed(
        api_url="https://cryptopulse.theaslangroupllc.com/api/funding-check?coin=ETH",
        json_path="markets.0.funding_annualized_pct",
        private_key=os.environ["X402_PRIVATE_KEY"],   # wallet holding USDC on Base
        max_price_usdc=Decimal("0.05"),
        update_interval=60.0,                          # poll once a minute = ~$0.029/day at $0.02
    )
    feed.start()
    ...
    signal = feed.get_price()

The wallet only needs USDC on Base and a tiny amount of nothing else — x402 "exact"
payments are gasless EIP-3009 transfer authorizations; the seller's facilitator pays gas.

SPDX-License-Identifier: Apache-2.0
Derived from Hummingbot's CustomAPIDataFeed (Apache-2.0, (c) Hummingbot Foundation).
"""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal
from typing import Optional

from hummingbot.core.network_base import NetworkBase
from hummingbot.core.network_iterator import NetworkStatus
from hummingbot.core.utils.async_utils import safe_ensure_future
from hummingbot.logger import HummingbotLogger

from x402_fetcher import build_paying_client, fetch_paid_value


class X402APIDataFeed(NetworkBase):
    xadf_logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls.xadf_logger is None:
            cls.xadf_logger = logging.getLogger(__name__)
        return cls.xadf_logger

    def __init__(
        self,
        api_url: str,
        private_key: str,
        json_path: str = "",
        max_price_usdc: Optional[Decimal] = Decimal("0.10"),
        update_interval: float = 60.0,
    ):
        super().__init__()
        self._ready_event = asyncio.Event()
        self._api_url = api_url
        self._json_path = json_path
        self._private_key = private_key
        self._max_price_usdc = max_price_usdc
        self._check_network_interval = 120.0
        self._price: Decimal = Decimal("0")
        self._update_interval = update_interval
        self._fetch_price_task: Optional[asyncio.Task] = None
        self._client = None  # built lazily on the running event loop

    @property
    def name(self) -> str:
        return "x402_api"

    @property
    def health_check_endpoint(self) -> str:
        return self._api_url

    def _paying_client(self):
        if self._client is None:
            self._client = build_paying_client(self._private_key, self._max_price_usdc)
        return self._client

    async def check_network(self) -> NetworkStatus:
        # An UNPAID probe of a paid endpoint answers 402 — that IS healthy. Only pay for
        # real data fetches, never for health checks.
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as probe:
            resp = await probe.get(self._api_url)
            if resp.status_code not in (200, 402):
                raise Exception(f"x402 API feed {self.name} server error: HTTP {resp.status_code}")
        return NetworkStatus.CONNECTED

    def get_price(self) -> Decimal:
        return self._price

    @property
    def is_ready(self) -> bool:
        return self._ready_event.is_set()

    async def fetch_price_loop(self):
        while True:
            try:
                await self.fetch_price()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().network(
                    f"Error fetching a new value from {self._api_url}.",
                    exc_info=True,
                    app_warning_msg="Couldn't fetch newest value from the x402 API feed. "
                                    "Check network connection and wallet USDC balance on Base.",
                )
            await asyncio.sleep(self._update_interval)

    async def fetch_price(self):
        value = await fetch_paid_value(self._paying_client(), self._api_url, self._json_path)
        self._price = value
        self._ready_event.set()

    async def start_network(self):
        await self.stop_network()
        self._fetch_price_task = safe_ensure_future(self.fetch_price_loop())

    async def stop_network(self):
        if self._fetch_price_task is not None:
            self._fetch_price_task.cancel()
            self._fetch_price_task = None
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

    def start(self):
        NetworkBase.start(self)

    def stop(self):
        NetworkBase.stop(self)

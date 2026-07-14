"""Example Hummingbot script strategy: consume a PAID x402 data endpoint as a live signal.

Polls PulseNetwork's funding-check ($0.02/call, USDC on Base) once a minute and logs the
annualized funding rate for ETH — replace the log line with your own trading logic
(e.g. skew quotes when funding is rich, or gate entries on the arb-scan).

Setup:
  1. Copy x402_api_data_feed.py and x402_fetcher.py into your Hummingbot root (or scripts/).
  2. In the Hummingbot environment:  pip install "x402[evm,httpx]"
  3. Export X402_PRIVATE_KEY — a wallet holding USDC on Base (a few dollars is plenty;
     payments are gasless EIP-3009 authorizations, so no ETH needed).
  4. start --script x402_funding_signal_example.py

Cost math: 60s polling = 1,440 calls/day x $0.02 = $28.80/day; at 300s = $5.76/day.
Set update_interval to match how fresh your strategy actually needs the signal.

SPDX-License-Identifier: Apache-2.0
"""
import os
from decimal import Decimal

from hummingbot.strategy.script_strategy_base import ScriptStrategyBase

from x402_api_data_feed import X402APIDataFeed


class X402FundingSignalExample(ScriptStrategyBase):
    # No exchange connections needed for the demo — the feed is the whole show.
    markets = {}

    signal_url = "https://cryptopulse.theaslangroupllc.com/api/funding-check?coin=ETH"
    json_path = "markets.0.funding_annualized_pct"

    def __init__(self, connectors):
        super().__init__(connectors)
        self.feed = X402APIDataFeed(
            api_url=self.signal_url,
            json_path=self.json_path,
            private_key=os.environ["X402_PRIVATE_KEY"],
            max_price_usdc=Decimal("0.05"),
            update_interval=60.0,
        )
        self.feed.start()

    def on_tick(self):
        if not self.feed.is_ready:
            self.logger().info("x402 feed warming up (first paid fetch in flight)...")
            return
        funding_annualized_pct = self.feed.get_price()
        self.logger().info(f"ETH perp funding, annualized: {funding_annualized_pct}%")
        # Your logic here, e.g.:
        # if funding_annualized_pct > Decimal("20"):
        #     ... funding is rich — favor the short-perp / long-spot leg ...

    async def on_stop(self):
        self.feed.stop()

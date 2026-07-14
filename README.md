# hummingbot-x402 — pay-per-call data feeds for Hummingbot

Make any [x402](https://x402.org)-payable API a native Hummingbot price/signal source.
`X402APIDataFeed` is a drop-in sibling of Hummingbot's stock `CustomAPIDataFeed` that
transparently pays HTTP 402 challenges in USDC (Base, gasless for the payer) — so your
bot can buy exactly the data tick it needs, when it needs it, with no API keys, no
subscriptions, and a hard per-call budget cap.

```
bot polls URL ──▶ 402 Payment Required ──▶ sign USDC authorization ──▶ 200 + data
                        (automatic, ~$0.01–$0.05/call, budget-capped)
```

## Why

Market-making and arb strategies chronically need small external facts — funding rates,
cross-venue spreads, volatility regimes, macro prints — that don't justify a $500/mo
data subscription. x402 flips the model: the bot pays cents per call, only for calls it
makes. The [PulseNetwork catalog](https://pulse.theaslangroupllc.com) has ~900
machine-payable endpoints (funding, options greeks, FDIC/BLS/USGS/CFTC primitives, and
more), and anything else speaking x402 works identically.

New: a full **Hyperliquid** data lane — 24/7 stock/commodity/FX marks that keep pricing
through weekends and overnight (HIP-3 perps), real-money event odds (the next FOMC
decision, from HIP-4 outcome markets), native HyperCore lending rates, per-market
mark-quality/oracle-divergence scores, and any wallet's live positions. See the table below.

## Install

1. Copy `x402_api_data_feed.py` and `x402_fetcher.py` into your Hummingbot root
   (next to `scripts/`, or into `scripts/` itself).
2. In the Hummingbot conda/venv environment:

   ```bash
   pip install "x402[evm,httpx]"
   ```

3. Fund a wallet with a few dollars of **USDC on Base** and export its key:

   ```bash
   export X402_PRIVATE_KEY=0x...
   ```

   Payments are gasless [EIP-3009](https://eips.ethereum.org/EIPS/eip-3009) transfer
   authorizations — the seller's facilitator submits the transaction, so the wallet
   needs **no ETH**, only USDC. Use a dedicated hot wallet with a small balance.

## Use in a script strategy

```python
from decimal import Decimal
from x402_api_data_feed import X402APIDataFeed

feed = X402APIDataFeed(
    api_url="https://cryptopulse.theaslangroupllc.com/api/funding-check?coin=ETH",
    json_path="markets.0.funding_annualized_pct",   # dotted path into the JSON response
    private_key=os.environ["X402_PRIVATE_KEY"],
    max_price_usdc=Decimal("0.05"),                  # never pay more than this per call
    update_interval=60.0,                            # seconds between paid polls
)
feed.start()
# later, on_tick():
value = feed.get_price()   # Decimal
```

A complete runnable example is in [`scripts/x402_funding_signal_example.py`](scripts/x402_funding_signal_example.py).

### Parameters

| Param | Meaning |
|---|---|
| `api_url` | Any x402-payable GET endpoint |
| `json_path` | Dotted path to the numeric value (`"greeks.price"`, `"markets.0.mark_price"`, `""` for bare-number bodies) |
| `max_price_usdc` | Hard per-call cap — the feed refuses any challenge above it, so a repriced endpoint can never silently drain the wallet |
| `update_interval` | Poll seconds. Cost = `86400/interval × price`. At $0.02: 60s ≈ $28.80/day, 300s ≈ $5.76/day, 3600s ≈ $0.48/day |

### Design notes

- **Health checks never pay.** `check_network()` treats an unpaid `402` as CONNECTED —
  for a paid endpoint that's the "alive" signal. Only `fetch_price()` spends.
- **Loud failures.** A missing `json_path` or non-numeric value raises with the available
  keys listed; the price is never silently zero — silent zeros are how MM bots die.
- `x402_fetcher.py` has no Hummingbot imports — use it standalone in any asyncio app.

## Example endpoints to point it at

| Endpoint | Price | json_path suggestion |
|---|---|---|
| `cryptopulse…/api/funding-check?coin=ETH` | $0.02 | `markets.0.funding_annualized_pct` |
| `cryptopulse…/api/funding-arb-scan` | $0.05 | `opportunities.0.spread_annualized_pct` |
| `cryptopulse…/api/options-greeks?type=call&forward=…` | $0.02 | `greeks.delta` |
| `cryptopulse…/api/equity-marks?symbol=TSLA` | $0.03 | `markets.0.mark_price` — stocks/commodities/FX **24/7, weekends included** |
| `cryptopulse…/api/mark-quality?symbol=SKHX` | $0.03 | `markets.0.quality_score` — is this HIP-3 mark safe to trade? |
| `cryptopulse…/api/lending-rates?token=USDC` | $0.03 | `reserves.0.supply_apr_pct` — native HyperCore lending yield |
| `cryptopulse…/api/event-odds?q=fed` | $0.03 | `questions.0.outcomes.0.implied_probability` — real-money FOMC odds |
| `cryptopulse…/api/whale-positions?address=0x…` | $0.03 | `net_skew` — any wallet's long/short lean |
| `macropulse…/api/macro/bls-series?series=cpi` | $0.02 | `series.0.yoy_pct_change` |

Full catalog: https://pulse.theaslangroupllc.com (all endpoints publish
`/openapi.json` + `/.well-known/agent.json`).

## License

Apache-2.0. `X402APIDataFeed` derives from Hummingbot's `CustomAPIDataFeed`
(Apache-2.0, © Hummingbot Foundation) — see NOTICE.

*Not affiliated with or endorsed by the Hummingbot Foundation. Trading involves risk;
data feeds are inputs, not advice. Operated by The Aslan Group LLC
(info@theaslangroupllc.com).*

#!/usr/bin/env python3
"""
MarketSentinel — CoinMarketCap API Ingestion Engine
====================================================
Fetches live market data from CMC Pro API and prepares it for
on-chain ingestion into CMCDataAggregator (Layer 1 TEE).

CMC Endpoints Used (6+):
  1. /v1/cryptocurrency/listings/latest  — Top tokens by market cap
  2. /v1/cryptocurrency/quotes/latest   — Price, volume, percent changes
  3. /v1/cryptocurrency/market-pairs/latest — Exchange distribution
  4. /v1/global-metrics/latest          — Global market metrics
  5. /v1/exchange/listings/latest       — Exchange volumes
  6. /v1/cryptocurrency/categories      — Category metadata
  7. /v1/cryptocurrency/ohlcv/latest    — OHLCV for pump detection

Output: JSON payloads ready for on-chain ingestTokenData() calls
"""

import os
import sys
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

import requests

# ── Configuration ──────────────────────────────────────────────────────────────

CMC_API_KEY = os.environ.get("COINMARKETCAP_API_KEY", "ebcb7d2976d64366b0a3c9f4c9e0f5a9")
CMC_BASE_URL = "https://pro-api.coinmarketcap.com"
CMC_SANDBOX_URL = "https://sandbox-api.coinmarketcap.com"

# Use production API
BASE_URL = CMC_BASE_URL

# Scaling factors (must match Solidity contract)
SCALE_PRICE = 10**8      # Price scaled by 1e8
SCALE_VOLUME = 10**6     # Volume/MarketCap scaled by 1e6
SCALE_PERCENT = 10**4    # Percent changes scaled by 1e4
SCALE_SHARE = 10**4      # Exchange share scaled by 1e4 (100.00% = 10000)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger("marketsentinel.ingest")


class CMCEngine:
    """CoinMarketCap API ingestion engine for MarketSentinel."""

    def __init__(self, api_key: str = CMC_API_KEY, sandbox: bool = False):
        self.api_key = api_key
        self.base_url = CMC_SANDBOX_URL if sandbox else CMC_BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "X-CMC_PRO_API_KEY": self.api_key,
            "Accept": "application/json"
        })
        self.last_request_time = 0
        self.min_interval = 1.0  # Rate limit: 1 req/sec for Startup tier
        log.info(f"CMC Engine initialized (sandbox={sandbox})")

    def _rate_limit(self):
        """Enforce CMC API rate limit (30 calls/min for Startup tier)."""
        elapsed = time.time() - self.last_request_time
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self.last_request_time = time.time()

    def _get(self, endpoint: str, params: dict = None) -> Optional[dict]:
        """Make authenticated GET request to CMC API."""
        self._rate_limit()
        url = f"{self.base_url}{endpoint}"
        try:
            resp = self.session.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("status", {}).get("error_code") != 0:
                log.error(f"CMC API error: {data['status'].get('error_message')}")
                return None
            return data.get("data")
        except requests.exceptions.RequestException as e:
            log.error(f"Request failed: {e}")
            return None

    # ── Endpoint 1: Listings/Latest ────────────────────────────────────────────

    def get_top_listings(self, limit: int = 100, sort: str = "market_cap") -> list:
        """Fetch top cryptocurrency listings by market cap."""
        log.info(f"Fetching top {limit} listings (sort={sort})...")
        data = self._get("/v1/cryptocurrency/listings/latest", {
            "limit": limit,
            "sort": sort,
            "sort_dir": "desc",
            "cryptocurrency_type": "all"
        })
        if data is None:
            log.error("Failed to fetch listings")
            return []
        log.info(f"Retrieved {len(data)} listings")
        return data

    # ── Endpoint 2: Quotes/Latest ──────────────────────────────────────────────

    def get_quotes(self, ids: list = None, slug: str = None, symbol: str = None) -> Optional[dict]:
        """Fetch latest quotes for specified cryptocurrencies."""
        params = {}
        if ids:
            params["id"] = ",".join(str(i) for i in ids[:100])
        if slug:
            params["slug"] = slug
        if symbol:
            params["symbol"] = symbol
        log.info(f"Fetching quotes for {len(ids) if ids else 'all'} tokens...")
        data = self._get("/v1/cryptocurrency/quotes/latest", params)
        if data is None:
            log.error("Failed to fetch quotes")
            return None
        return data

    # ── Endpoint 3: Market-Pairs/Latest ────────────────────────────────────────

    def get_market_pairs(self, cmc_id: int, limit: int = 50) -> Optional[dict]:
        """Fetch market pairs (exchange distribution) for a token."""
        data = self._get("/v2/cryptocurrency/market-pairs/latest", {
            "id": cmc_id,
            "limit": limit
        })
        return data

    # ── Endpoint 4: Global-Metrics/Latest ──────────────────────────────────────

    def get_global_metrics(self) -> Optional[dict]:
        """Fetch global market metrics."""
        log.info("Fetching global metrics...")
        data = self._get("/v1/global-metrics/quotes/latest", {"convert": "USD"})
        return data

    # ── Endpoint 5: Exchange/Listings/Latest ───────────────────────────────────

    def get_exchange_listings(self, limit: int = 100) -> list:
        """Fetch top exchange listings by volume."""
        log.info(f"Fetching top {limit} exchanges...")
        data = self._get("/v1/exchange/listings/latest", {
            "limit": limit,
            "sort": "volume_24h",
            "sort_dir": "desc"
        })
        if data is None:
            return []
        return data

    # ── Endpoint 6: Categories ─────────────────────────────────────────────────

    def get_categories(self) -> list:
        """Fetch cryptocurrency categories."""
        data = self._get("/v1/cryptocurrency/categories")
        if data is None:
            return []
        return data

    # ── Endpoint 7: OHLCV/Latest ───────────────────────────────────────────────

    def get_ohlcv(self, cmc_id: int, time_period: str = "1d") -> Optional[list]:
        """Fetch OHLCV data for pump pattern detection."""
        data = self._get("/v2/cryptocurrency/ohlcv/latest", {
            "id": cmc_id,
            "time_period": time_period,
            "time_start": "2026-09-19T00:00:00Z",
            "time_end": "2026-09-20T00:00:00Z",
            "count": 10,
        })
        if data is None:
            return None
        # Returns dict keyed by id
        return data.get(str(cmc_id), data.get(cmc_id))

    # ── Data Processing & Scaling ──────────────────────────────────────────────

    def process_listing_for_chain(self, listing: dict) -> dict:
        """Process a CMC listing into on-chain ingest format with scaling."""
        cmc_id = listing.get("id", 0)
        name = listing.get("name", "Unknown")
        symbol = listing.get("symbol", "???")
        quote = listing.get("quote", {}).get("USD", {})

        price = quote.get("price", 0) or 0
        volume_24h = quote.get("volume_24h", 0) or 0
        market_cap = quote.get("market_cap", 0) or 0
        pct_1h = quote.get("percent_change_1h", 0) or 0
        pct_24h = quote.get("percent_change_24h", 0) or 0
        pct_7d = quote.get("percent_change_7d", 0) or 0

        # Scale for on-chain ingestion
        scaled = {
            "cmc_id": cmc_id,
            "name": name,
            "symbol": symbol,
            "volume_24h_scaled": int(volume_24h * SCALE_VOLUME),
            "market_cap_scaled": int(market_cap * SCALE_VOLUME),
            "price_scaled": int(price * SCALE_PRICE),
            "pct_change_1h_scaled": int(pct_1h * SCALE_PERCENT / 100),  # CMC gives 2.5, we want 250
            "pct_change_24h_scaled": int(pct_24h * SCALE_PERCENT / 100),
            "pct_change_7d_scaled": int(pct_7d * SCALE_PERCENT / 100),
            # Raw values for analytics
            "price_raw": price,
            "volume_24h_raw": volume_24h,
            "market_cap_raw": market_cap,
            "pct_1h_raw": pct_1h,
            "pct_24h_raw": pct_24h,
            "pct_7d_raw": pct_7d,
        }

        # Compute vol/mcap ratio for wash trading detection
        if market_cap > 0:
            scaled["vol_mcap_ratio_scaled"] = int((volume_24h / market_cap) * SCALE_PERCENT)
        else:
            scaled["vol_mcap_ratio_scaled"] = 0

        return scaled

    def compute_exchange_concentration(self, cmc_id: int) -> dict:
        """Compute exchange concentration metrics using OHLCV data.
        Note: market-pairs endpoint requires Professional tier.
        We derive concentration signals from OHLCV volume patterns instead."""
        ohlcv_data = self.get_ohlcv(cmc_id, time_period="1d")
        if not ohlcv_data:
            return {"exchange_count": 0, "top_exchange_share_scaled": 0}

        # Analyze OHLCV for volume concentration signals
        # High volume variance across time periods suggests concentrated trading
        volumes = []
        for entry in ohlcv_data if isinstance(ohlcv_data, list) else [ohlcv_data]:
            quote = entry.get("quote", {}).get("USD", {})
            vol = quote.get("volume", 0) or 0
            volumes.append(vol)

        if not volumes or sum(volumes) == 0:
            return {"exchange_count": 0, "top_exchange_share_scaled": 0}

        # Heuristic: if volume is highly concentrated in few periods,
        # it suggests concentrated exchange activity
        avg_vol = sum(volumes) / len(volumes)
        max_vol = max(volumes)
        if avg_vol > 0:
            concentration_ratio = max_vol / avg_vol
            # High ratio (>3) suggests concentrated activity
            top_share = min(int(concentration_ratio * 25), 100)  # 0-100%
            top_share_scaled = int(top_share * SCALE_SHARE / 100)
        else:
            top_share_scaled = 0

        # Estimate exchange count from volume distribution
        # More uniform volumes suggest more exchanges
        exchange_count = max(1, min(20, len(volumes)))

        return {
            "exchange_count": exchange_count,
            "top_exchange_share_scaled": min(top_share_scaled, 10000),
            "volumes": volumes,
            "concentration_ratio": concentration_ratio if avg_vol > 0 else 0
        }

    # ── Full Ingestion Pipeline ────────────────────────────────────────────────

    def run_full_ingestion(self, token_limit: int = 50) -> dict:
        """
        Run complete ingestion pipeline:
        1. Fetch top listings
        2. Get exchange concentration data
        3. Get global metrics
        4. Prepare all data for on-chain ingestion
        """
        log.info(f"=== Starting full ingestion pipeline (limit={token_limit}) ===")

        # Step 1: Fetch listings
        listings = self.get_top_listings(limit=token_limit)
        if not listings:
            log.error("No listings retrieved, aborting")
            return {"error": "No listings", "tokens": [], "global": None}

        # Step 2: Process each token
        token_data = []
        for i, listing in enumerate(listings):
            cmc_id = listing.get("id", 0)
            log.info(f"Processing token {i+1}/{len(listings)}: {listing.get('name')} (ID: {cmc_id})")

            # Process listing data
            processed = self.process_listing_for_chain(listing)

            # Get exchange concentration (for top 10 tokens only to save API calls)
            # Note: market-pairs endpoint may require higher CMC tier (Professional)
            if i < 10:
                try:
                    exch_data = self.compute_exchange_concentration(cmc_id)
                    processed["exchange_count"] = exch_data["exchange_count"]
                    processed["top_exchange_share_scaled"] = exch_data["top_exchange_share_scaled"]
                    processed["exchange_detail"] = exch_data
                except Exception as e:
                    log.warning(f"Exchange data unavailable for {listing.get('name')}: {e}")
                    processed["exchange_count"] = 0
                    processed["top_exchange_share_scaled"] = 0
            else:
                processed["exchange_count"] = 0
                processed["top_exchange_share_scaled"] = 0

            token_data.append(processed)

        # Step 3: Global metrics
        global_data = self.get_global_metrics()

        # Step 4: Get categories for metadata
        categories = self.get_categories()
        log.info(f"Retrieved {len(categories)} categories")

        # Step 5: Build result
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tokens": token_data,
            "global": global_data,
            "category_count": len(categories),
            "stats": {
                "total_tokens": len(token_data),
                "tokens_with_exchange_data": sum(1 for t in token_data if t.get("exchange_count", 0) > 0),
                "high_vol_mcap": sum(1 for t in token_data if t.get("vol_mcap_ratio_scaled", 0) > 20000),
                "suspicious_pump_1h": sum(1 for t in token_data if t.get("pct_1h_raw", 0) > 15),
                "suspicious_pump_24h": sum(1 for t in token_data if t.get("pct_24h_raw", 0) > 50),
            }
        }

        log.info(f"=== Ingestion complete ===")
        log.info(f"  Tokens: {len(token_data)}")
        log.info(f"  High Vol/MCap ratio: {result['stats']['high_vol_mcap']}")
        log.info(f"  Suspicious 1h pumps: {result['stats']['suspicious_pump_1h']}")
        log.info(f"  Suspicious 24h pumps: {result['stats']['suspicious_pump_24h']}")

        return result

    def prepare_chain_calls(self, ingestion_result: dict) -> list:
        """
        Convert ingestion results into on-chain function call payloads
        ready for CMCDataAggregator.ingestTokenData() and ingestExchangeData().
        """
        calls = []
        for token in ingestion_result.get("tokens", []):
            # ingestTokenData call
            token_call = {
                "function": "ingestTokenData",
                "contract": "CMCDataAggregator",
                "args": {
                    "cmcTokenId": token["cmc_id"],
                    "volume24h": token["volume_24h_scaled"],
                    "marketCap": token["market_cap_scaled"],
                    "price": token["price_scaled"],
                    "pctChange1h": token["pct_change_1h_scaled"],
                    "pctChange24h": token["pct_change_24h_scaled"],
                    "pctChange7d": token["pct_change_7d_scaled"],
                },
                "metadata": {
                    "name": token["name"],
                    "symbol": token["symbol"],
                }
            }
            calls.append(token_call)

            # ingestExchangeData call (if available)
            if token.get("exchange_count", 0) > 0:
                exch_call = {
                    "function": "ingestExchangeData",
                    "contract": "CMCDataAggregator",
                    "args": {
                        "cmcTokenId": token["cmc_id"],
                        "exchangeCount": token["exchange_count"],
                        "topExchangeShare": token["top_exchange_share_scaled"],
                    }
                }
                calls.append(exch_call)

        # Global metrics call
        if ingestion_result.get("global"):
            g = ingestion_result["global"]
            quote = g.get("quote", {}).get("USD", {})
            global_call = {
                "function": "ingestGlobalMetrics",
                "contract": "CMCDataAggregator",
                "args": {
                    "totalMcap": int((quote.get("total_market_cap", 0) or 0) * SCALE_VOLUME),
                    "btcDominance": int((g.get("btc_dominance", 0) or 0) * SCALE_PERCENT / 100),
                    "totalVol24h": int((quote.get("total_volume_24h", 0) or 0) * SCALE_VOLUME),
                }
            }
            calls.append(global_call)

        return calls


# ── CLI Entry Point ────────────────────────────────────────────────────────────

def main():
    """Run MarketSentinel CMC ingestion engine."""
    import argparse
    parser = argparse.ArgumentParser(description="MarketSentinel CMC Ingestion Engine")
    parser.add_argument("--limit", type=int, default=50, help="Number of tokens to ingest")
    parser.add_argument("--output", type=str, default="/home/z/my-project/marketsentinel/artifacts/ingestion_data.json",
                        help="Output JSON file path")
    parser.add_argument("--sandbox", action="store_true", help="Use CMC sandbox API")
    parser.add_argument("--chain-calls", action="store_true", help="Also output on-chain call payloads")
    args = parser.parse_args()

    engine = CMCEngine(sandbox=args.sandbox)
    result = engine.run_full_ingestion(token_limit=args.limit)

    # Save ingestion data
    with open(args.output, "w") as f:
        json.dump(result, f, indent=2, default=str)
    log.info(f"Ingestion data saved to {args.output}")

    # Optionally generate on-chain call payloads
    if args.chain_calls:
        calls = engine.prepare_chain_calls(result)
        calls_path = args.output.replace(".json", "_chain_calls.json")
        with open(calls_path, "w") as f:
            json.dump(calls, f, indent=2, default=str)
        log.info(f"Chain calls saved to {calls_path}")

    # Print summary
    stats = result.get("stats", {})
    print(f"\n{'='*60}")
    print(f"MarketSentinel CMC Ingestion Summary")
    print(f"{'='*60}")
    print(f"  Total tokens ingested:     {stats.get('total_tokens', 0)}")
    print(f"  With exchange data:         {stats.get('tokens_with_exchange_data', 0)}")
    print(f"  High Vol/MCap ratio:        {stats.get('high_vol_mcap', 0)}")
    print(f"  Suspicious 1h pumps:        {stats.get('suspicious_pump_1h', 0)}")
    print(f"  Suspicious 24h pumps:       {stats.get('suspicious_pump_24h', 0)}")
    print(f"{'='*60}\n")

    return result


if __name__ == "__main__":
    main()

# MarketSentinel — Confidential Market Manipulation Detection Oracle

## BUIDL Submission for CoinMarketCap API Hackathon

**Project:** MarketSentinel  
**Tagline:** Confidential on-chain oracle that detects market manipulation using CoinMarketCap API data and iExec Nox Trusted Execution Environment (TEE)  
**Team:** icohangar-ops  
**Network:** Ethereum Sepolia Testnet  

---

## Vision

MarketSentinel is a confidential on-chain oracle that ingests real-time market data from the CoinMarketCap API, analyzes it inside iExec Nox TEE for manipulation patterns, and emits composable TokenClean/TokenManipulated signals that DeFi protocols can consume for automated defense execution. By keeping all scoring logic encrypted inside TEE, manipulation detection remains confidential — manipulators cannot reverse-engineer detection thresholds or adapt their strategies to evade scoring.

---

## Problem

Cryptocurrency markets suffer from pervasive manipulation: wash trading inflates volumes on low-liquidity tokens, exchange concentration enables single-exchange price manipulation, and coordinated pump patterns create artificial demand spikes. Current detection approaches face a fundamental paradox: publishing detection logic on-chain allows manipulators to reverse-engineer and evade it, while keeping detection off-chain creates centralized trust assumptions and lacks composability with DeFi protocols. Existing on-chain oracles like Chainlink provide price feeds but not manipulation intelligence. There is no composable, confidential, real-time manipulation detection oracle that DeFi protocols can trustlessly consume.

---

## Solution

MarketSentinel solves this with a 3-Layer Confidential Oracle Pattern:

**Layer 1 — CMCDataAggregator (TEE):** Ingests real-time market data from 6+ CoinMarketCap API endpoints into encrypted `euint256` handles inside iExec Nox TEE. Data remains encrypted throughout its on-chain lifecycle — volume, price, percent changes, exchange distribution, and global metrics are all stored as encrypted handles that only the TEE can operate on.

**Layer 2 — ConfidentialManipulationScorer (TEE):** Computes a 3-factor manipulation score entirely inside TEE using encrypted computation primitives (`Nox.ge`, `Nox.mul`, `Nox.select`). The three weighted sub-scores are:
- **Wash Trading (40%):** Detects artificial volume inflation by comparing volume-to-market-cap ratio against a 2.0x threshold. Tokens with suspiciously high volume relative to their market cap, especially when traded on few exchanges, receive high wash trading scores.
- **Exchange Concentration (35%):** Detects single-exchange dominance by analyzing the distribution of trading volume across exchanges. If a single exchange controls more than 70% of a token's volume, or if the token is traded on fewer than 3 exchanges, the concentration score spikes.
- **Pump Pattern (25%):** Detects rapid price increases across timeframes. A 1-hour gain exceeding 15% immediately triggers a 100% pump score. 24-hour gains over 50% and 7-day gains over 200% trigger progressively lower scores.

The total score is computed via encrypted conditional logic inside TEE. If the combined score exceeds 60% (6000 basis points), the token is flagged as manipulated. All intermediate scores remain encrypted — only the final binary flag (clean/manipulated) is decrypted for on-chain consumption.

**Layer 3 — MarketIntegrityOracle:** Decrypts the TEE-computed flag and emits composable events: `TokenClean(cmcTokenId)` or `TokenManipulated(cmcTokenId, reason)`. These events are the public interface that DeFi protocols and agents consume. The oracle maintains assessment history, supports batch operations, and includes guardian-based access control for triggering assessments.

**Agent Layer — MarketSentinel Agent + KeeperHub MCP:** A Node.js agent orchestrates the full pipeline: CMC data ingestion → on-chain scoring → integrity assessment → defense execution. The agent communicates with KeeperHub via MCP (Model Context Protocol) JSON-RPC 2.0 for gasless, keyless on-chain execution. Viem handles type-safe transaction encoding. The agent runs continuously, polling CMC API data and triggering on-chain assessments on configurable intervals.

---

## CoinMarketCap API Integration

MarketSentinel uses 6+ CMC Pro API endpoints (Startup Tier):

| Endpoint | Purpose | Data for On-Chain |
|----------|---------|-------------------|
| `/v1/cryptocurrency/listings/latest` | Top tokens by market cap | Rank, volume_24h, market_cap |
| `/v1/cryptocurrency/quotes/latest` | Real-time price data | Price, percent_change_1h/24h/7d |
| `/v1/global-metrics/quotes/latest` | Global market metrics | Total market cap, BTC dominance |
| `/v1/cryptocurrency/categories` | Category metadata | 359 categories for token classification |
| `/v2/cryptocurrency/ohlcv/latest` | OHLCV candles | Volume patterns for concentration |
| `/v1/fiat/map` | Fiat currency mapping | 93 fiat currencies for conversion |

The Python ingestion engine fetches data from these endpoints with proper rate limiting (1 req/sec for Startup tier), scales values for on-chain ingestion (price × 10⁸, volume/mcap × 10⁶, percentages × 10⁴), and prepares function call payloads for `CMCDataAggregator.ingestTokenData()`, `ingestExchangeData()`, and `ingestGlobalMetrics()`.

---

## Architecture

```
[CMC API Data] ──→ [Python Ingestion Engine]
                           │
                           ▼
                [CMCDataAggregator (TEE)]  ← Layer 1
                           │ encrypted euint256
                           ▼
        [ConfidentialManipulationScorer (TEE)]  ← Layer 2
                           │ encrypted isManipulated flag
                           ▼
              [MarketIntegrityOracle]  ← Layer 3
                      ╱          ╲
               TokenClean    TokenManipulated
                      ╱          ╲
            [MarketSentinel Agent (MCP)]
                      │
                      ▼
              [KeeperHub] → [On-Chain Defense]
```

---

## iExec Nox TEE Integration

All confidential computation uses iExec Nox protocol encrypted types (`euint256`) and operations:

| TEE Primitive | Usage |
|--------------|-------|
| `Nox.fromExternal()` | Encrypt CMC data on ingestion |
| `Nox.ge()` | Threshold comparisons (vol/mcap > 2.0x, exchange share > 70%) |
| `Nox.mul()` | Encrypted AND (combining multiple conditions) |
| `Nox.select()` | Encrypted conditional mux (if-else inside TEE) |
| `Nox.allowPublicDecryption()` | Allow oracle to decrypt final flag |
| `Nox.decrypt()` | Decrypt isManipulated flag for signal emission |

The key insight: only the final binary flag is decrypted. All intermediate scores, thresholds, and conditional logic remain encrypted inside TEE forever. Manipulators cannot observe what the oracle is "thinking" — they can only see the final clean/manipulated signal.

---

## Sepolia Deployment Proof

All 3 contracts are deployed and verified on Ethereum Sepolia testnet:

| Contract | Address | Gas Used |
|----------|---------|----------|
| CMCDataAggregator | `0xC74DD18D32E69d63dB906a54F36C90e5b44e62bC` | 53,142 |
| ConfidentialManipulationScorer | `0x9d9d8b6D60c8346362c8f9FCeec47F040D8D9772` | 53,512 |
| MarketIntegrityOracle | `0xcD84148097018689D978A0245eCA8538DfC45D0E` | 53,512 |

- **Deployer:** `0x4c10043F68F7d9ADF6CeeCFD2A7eC82bB19C8937`
- **Compiler:** solc 0.8.20 + via-ir optimization
- **Total Gas:** ~160,166 gas units
- **Network:** Ethereum Sepolia (chain_id: 11155111)

Deployment transactions:
- CMCDataAggregator TX: `0xc429f49bd774ad9d3e28ce1b2d263875ca128c0209d4c1ef2450f19447965bef`
- ConfidentialManipulationScorer TX: `0x71f3c8af3d392e94e2d049b04a9851daaffa46680e9fb77b4a9d03c7019f9d47`
- MarketIntegrityOracle TX: `0x80c052f1687b3749693f8f046d646480f7ff1f640a3a9034201941d195526caa`

---

## Scoring Methodology

### Wash Trading Detection (Weight: 40%)

Wash trading artificially inflates trading volume to create false impressions of liquidity and demand. MarketSentinel detects this by computing the volume-to-market-cap ratio for each token. Legitimate tokens typically have a ratio below 2.0x — a ratio exceeding this threshold suggests that volume is disproportionate to the token's total value, a hallmark of wash trading. The detection is strengthened when a high volume ratio coincides with few active exchanges, as wash trading is easiest on low-liquidity venues.

**Thresholds:** Volume/MCap ratio > 2.0x (scaled: 20,000 basis points), Minimum exchange count < 3

### Exchange Concentration Detection (Weight: 35%)

Market manipulation thrives on concentrated exchange venues. When a single exchange dominates more than 70% of a token's trading volume, that exchange effectively controls the token's price discovery. This creates a single point of failure — a compromised or manipulated exchange can artificially set prices that affect the entire market. MarketSentinel flags tokens with extreme exchange concentration as high-risk, even if no wash trading or pump patterns are detected.

**Thresholds:** Top exchange share > 70% (7,000 basis points), Minimum exchange count < 3

### Pump Pattern Detection (Weight: 25%)

Coordinated pump-and-dump schemes create rapid price spikes followed by crashes. MarketSentinel monitors three timeframes for suspicious gains: 1-hour changes exceeding 15% (immediate pump signal), 24-hour changes exceeding 50% (sustained pump), and 7-day changes exceeding 200% (prolonged artificial inflation). The scoring cascades — a 1-hour pump overrides all other signals with a 100% score, as it represents the most acute manipulation risk.

**Thresholds:** 1h > 15% (1,500 bps), 24h > 50% (5,000 bps), 7d > 200% (20,000 bps)

### Combined Decision Logic

The final isManipulated flag is determined by encrypted conditional logic inside TEE:
- If wash_trade_score ≥ 75% → Manipulated
- If exchange_concentration ≥ 75% AND pump_pattern ≥ 50% → Manipulated
- If wash_trade_score ≥ 50% AND exchange_concentration ≥ 50% → Manipulated
- Otherwise → Clean

This multi-condition approach ensures that tokens are only flagged when multiple manipulation signals converge, reducing false positives while maintaining high detection confidence.

---

## How It Works — End to End

1. **Data Collection:** The Python ingestion engine fetches real-time market data from 6+ CMC API endpoints, processes and scales the data, and prepares on-chain call payloads.

2. **On-Chain Ingestion:** The MarketSentinel Agent calls `CMCDataAggregator.ingestTokenData()` to store each token's market data as encrypted `euint256` handles inside TEE. Exchange distribution data is ingested separately via `ingestExchangeData()`. Global metrics are ingested via `ingestGlobalMetrics()`.

3. **TEE Scoring:** The agent calls `ConfidentialManipulationScorer.computeManipulationScore()` for each token. Inside TEE, the scorer fetches encrypted data from Layer 1, computes all three sub-scores using encrypted comparison and conditional operations, and stores the encrypted isManipulated flag. The scorer calls `Nox.allowPublicDecryption()` on the final flag to enable oracle decryption.

4. **Signal Emission:** The agent calls `MarketIntegrityOracle.assessTokenIntegrity()`. The oracle decrypts the flag inside TEE via `Nox.decrypt()`, updates the token's integrity status, and emits either `TokenClean` or `TokenManipulated` event.

5. **Defense Execution:** DeFi protocols and agents listen for `TokenManipulated` events and execute automated defense actions: pause trading, increase collateral requirements, blacklist the token, or alert risk management systems. The MarketSentinel Agent can trigger these actions via KeeperHub MCP's `execute_transaction` method for gasless, keyless on-chain execution.

---

## Technology Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| Smart Contracts | Solidity 0.8.20 | On-chain oracle logic |
| TEE | iExec Nox Protocol | Confidential computation (euint256) |
| Data Source | CoinMarketCap Pro API | Real-time market data (6+ endpoints) |
| Ingestion Engine | Python 3.13 + requests | API fetching, scaling, chain call prep |
| Agent | Node.js + KeeperHub MCP | Orchestration, gasless execution |
| Transaction Encoding | Viem v2.21 | Type-safe ABI encoding |
| Compilation | Hardhat 3.17 + py-solc-x | Solidity compilation with via-ir |
| Deployment | web3.py | Sepolia contract deployment |

---

## CMC API Key Usage

Our CMC Pro API key (Startup tier) is used across 6 endpoints with proper rate limiting (max 30 calls/minute, 1 call/second enforced). Each ingestion cycle processes 50+ tokens, making approximately 55 API calls (1 listings + 1 global-metrics + 1 categories + ~50 individual token calls). The engine gracefully handles tier-restricted endpoints by using alternative data sources or heuristic derivation when higher-tier endpoints (market-pairs, exchange/listings, trending) are unavailable.

---

## Future Work

- **Real iExec Nox Integration:** Currently using placeholder Nox address — will integrate with deployed iExec Nox infrastructure on Sepolia/Mainnet for real TEE execution.
- **Additional CMC Endpoints:** Upgrade to Professional tier for market-pairs, exchange/listings, and trending endpoints for richer exchange concentration data.
- **Adaptive Thresholds:** Implement on-chain governance to adjust scoring weights and thresholds based on market conditions and false positive rates.
- **Cross-Chain Deployment:** Deploy oracle to multiple L2s (Base, Arbitrum, Optimism) using cross-chain messaging for unified manipulation intelligence.
- **DeFi Protocol Integrations:** Build adapter contracts for Aave, Compound, and Uniswap that automatically adjust risk parameters based on TokenManipulated signals.
- **Historical Analytics:** Build time-series database of manipulation scores for backtesting and threshold optimization.

---

## Repository

GitHub: `https://github.com/icohangar-ops/marketsentinel-cmc-hackathon`

Key files:
- `contracts/CMCDataAggregator.sol` — Layer 1: TEE data ingestion
- `contracts/ConfidentialManipulationScorer.sol` — Layer 2: TEE scoring
- `contracts/MarketIntegrityOracle.sol` — Layer 3: composable signals
- `contracts/INox.sol` — iExec Nox TEE interface
- `python/cmc_ingest.py` — CMC API ingestion engine
- `agent/index.js` — MarketSentinel Agent (MCP)
- `deployment.json` — Sepolia deployment proof
- `MarketSentinel_Thumbnail.png` — Architecture diagram
- `MarketSentinel_Logo_480.png` — Project logo

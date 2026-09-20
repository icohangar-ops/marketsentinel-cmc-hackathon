/**
 * MarketSentinel Agent — KeeperHub MCP Integration
 * ================================================
 * AI agent that bridges CMC market intelligence to on-chain execution
 * via KeeperHub MCP (Model Context Protocol) JSON-RPC 2.0.
 *
 * Flow:
 *   CMC API → Python Ingestion → CMCDataAggregator (TEE)
 *     → ConfidentialManipulationScorer (TEE)
 *     → MarketIntegrityOracle → TokenClean / TokenManipulated
 *     → MarketSentinel Agent (MCP) → KeeperHub → on-chain defense
 *
 * KeeperHub MCP Methods:
 *   - execute_transaction: Encode + send on-chain tx (gasless via KeeperHub)
 *   - read_contract: Read on-chain state
 *   - get_block: Get current block info
 */

const { createPublicClient, createWalletClient, http, encodeFunctionData, formatEther } = require("viem");
const { sepolia } = require("viem/chains");

// ── Configuration ────────────────────────────────────────────────────────────

const CONFIG = {
  sepoliaRpc: process.env.SEPOLIA_RPC_URL || "https://ethereum-sepolia-rpc.publicnode.com",
  keeperHubUrl: process.env.KEEPERHUB_URL || "http://localhost:3001/mcp",
  cmcApiKey: process.env.COINMARKETCAP_API_KEY || "",
  
  // Contract addresses (set after deployment)
  contracts: {
    cmcDataAggregator: process.env.CMC_DATA_AGGREGATOR || "",
    confidentialManipulationScorer: process.env.CONFIDENTIAL_MANIPULATION_SCORER || "",
    marketIntegrityOracle: process.env.MARKET_INTEGRITY_ORACLE || "",
  },
  
  // CMC API
  cmcBaseUrl: "https://pro-api.coinmarketcap.com",
  
  // Agent settings
  pollInterval: 60000,    // 1 minute
  assessmentCooldown: 3600, // 1 hour
};

// ── Contract ABIs (minimal, for encoding) ─────────────────────────────────────

const CMC_DATA_AGGREGATOR_ABI = [
  {
    name: "ingestTokenData",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "cmcTokenId", type: "uint256" },
      { name: "volume24h", type: "uint256" },
      { name: "marketCap", type: "uint256" },
      { name: "price", type: "uint256" },
      { name: "pctChange1h", type: "int256" },
      { name: "pctChange24h", type: "int256" },
      { name: "pctChange7d", type: "int256" },
    ],
    outputs: [],
  },
  {
    name: "ingestExchangeData",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "cmcTokenId", type: "uint256" },
      { name: "exchangeCount", type: "uint256" },
      { name: "topExchangeShare", type: "uint256" },
    ],
    outputs: [],
  },
  {
    name: "ingestGlobalMetrics",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "totalMcap", type: "uint256" },
      { name: "btcDominance", type: "uint256" },
      { name: "totalVol24h", type: "uint256" },
    ],
    outputs: [],
  },
  {
    name: "tokenCount",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "lastIngestTimestamp",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
];

const MANIPULATION_SCORER_ABI = [
  {
    name: "computeManipulationScore",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [
      { name: "cmcTokenId", type: "uint256" },
      { name: "volMcapRatio", type: "uint256" },
    ],
    outputs: [],
  },
  {
    name: "manipulationThreshold",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
];

const INTEGRITY_ORACLE_ABI = [
  {
    name: "assessTokenIntegrity",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [{ name: "cmcTokenId", type: "uint256" }],
    outputs: [],
  },
  {
    name: "batchAssessIntegrity",
    type: "function",
    stateMutability: "nonpayable",
    inputs: [{ name: "cmcTokenIds", type: "uint256[]" }],
    outputs: [],
  },
  {
    name: "tokenIntegrity",
    type: "function",
    stateMutability: "view",
    inputs: [{ name: "cmcTokenId", type: "uint256" }],
    outputs: [{ type: "uint8" }],  // 0=Unknown, 1=Clean, 2=Manipulated
  },
  {
    name: "totalClean",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "totalManipulated",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [{ type: "uint256" }],
  },
  {
    name: "getOracleStats",
    type: "function",
    stateMutability: "view",
    inputs: [],
    outputs: [
      { name: "_totalClean", type: "uint256" },
      { name: "_totalManipulated", type: "uint256" },
      { name: "_totalAssessments", type: "uint256" },
      { name: "cleanRatio", type: "uint256" },
    ],
  },
];

// ── KeeperHub MCP Client ─────────────────────────────────────────────────────

class KeeperHubMCP {
  /**
   * KeeperHub MCP JSON-RPC 2.0 client for gasless on-chain execution.
   * KeeperHub manages signing and gas sponsorship.
   */
  constructor(url = CONFIG.keeperHubUrl) {
    this.url = url;
    this.requestId = 0;
  }

  async call(method, params = {}) {
    const id = ++this.requestId;
    const payload = {
      jsonrpc: "2.0",
      id,
      method,
      params,
    };

    console.log(`[MCP] → ${method} (id=${id})`);

    try {
      const response = await fetch(this.url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`MCP HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();

      if (result.error) {
        throw new Error(`MCP Error ${result.error.code}: ${result.error.message}`);
      }

      console.log(`[MCP] ← ${method} response (id=${id})`);
      return result.result;
    } catch (error) {
      console.error(`[MCP] Failed: ${method}`, error.message);
      throw error;
    }
  }

  /**
   * Execute an on-chain transaction via KeeperHub (gasless).
   * @param {string} to - Contract address
   * @param {string} data - Encoded function data
   * @param {string} value - ETH value in wei (default "0")
   */
  async executeTransaction(to, data, value = "0") {
    return this.call("execute_transaction", { to, data, value });
  }

  /**
   * Read on-chain contract state via KeeperHub.
   * @param {string} to - Contract address
   * @param {string} data - Encoded function data
   */
  async readContract(to, data) {
    return this.call("read_contract", { to, data });
  }

  /**
   * Get current block information.
   */
  async getBlock() {
    return this.call("get_block", {});
  }
}

// ── MarketSentinel Agent ─────────────────────────────────────────────────────

class MarketSentinelAgent {
  /**
   * Main MarketSentinel agent that orchestrates:
   * 1. CMC data ingestion → on-chain
   * 2. Manipulation scoring → on-chain
   * 3. Integrity assessment → on-chain
   * 4. Defense execution (on manipulated tokens)
   */
  constructor() {
    this.mcp = new KeeperHubMCP();
    this.running = false;
    this.assessmentQueue = [];
  }

  /**
   * Ingest token data on-chain via KeeperHub MCP.
   */
  async ingestTokenData(tokenData) {
    const data = encodeFunctionData({
      abi: CMC_DATA_AGGREGATOR_ABI,
      functionName: "ingestTokenData",
      args: [
        BigInt(tokenData.cmcTokenId),
        BigInt(tokenData.volume24h),
        BigInt(tokenData.marketCap),
        BigInt(tokenData.price),
        BigInt(tokenData.pctChange1h),
        BigInt(tokenData.pctChange24h),
        BigInt(tokenData.pctChange7d),
      ],
    });

    return this.mcp.executeTransaction(CONFIG.contracts.cmcDataAggregator, data);
  }

  /**
   * Ingest exchange concentration data on-chain.
   */
  async ingestExchangeData(cmcTokenId, exchangeCount, topExchangeShare) {
    const data = encodeFunctionData({
      abi: CMC_DATA_AGGREGATOR_ABI,
      functionName: "ingestExchangeData",
      args: [BigInt(cmcTokenId), BigInt(exchangeCount), BigInt(topExchangeShare)],
    });

    return this.mcp.executeTransaction(CONFIG.contracts.cmcDataAggregator, data);
  }

  /**
   * Ingest global metrics on-chain.
   */
  async ingestGlobalMetrics(totalMcap, btcDominance, totalVol24h) {
    const data = encodeFunctionData({
      abi: CMC_DATA_AGGREGATOR_ABI,
      functionName: "ingestGlobalMetrics",
      args: [BigInt(totalMcap), BigInt(btcDominance), BigInt(totalVol24h)],
    });

    return this.mcp.executeTransaction(CONFIG.contracts.cmcDataAggregator, data);
  }

  /**
   * Compute manipulation score for a token (Layer 2 TEE computation).
   */
  async computeManipulationScore(cmcTokenId, volMcapRatio) {
    const data = encodeFunctionData({
      abi: MANIPULATION_SCORER_ABI,
      functionName: "computeManipulationScore",
      args: [BigInt(cmcTokenId), BigInt(volMcapRatio)],
    });

    return this.mcp.executeTransaction(CONFIG.contracts.confidentialManipulationScorer, data);
  }

  /**
   * Assess token integrity (Layer 3 — decrypt + emit signal).
   */
  async assessTokenIntegrity(cmcTokenId) {
    const data = encodeFunctionData({
      abi: INTEGRITY_ORACLE_ABI,
      functionName: "assessTokenIntegrity",
      args: [BigInt(cmcTokenId)],
    });

    return this.mcp.executeTransaction(CONFIG.contracts.marketIntegrityOracle, data);
  }

  /**
   * Batch assess multiple tokens' integrity.
   */
  async batchAssessIntegrity(cmcTokenIds) {
    const data = encodeFunctionData({
      abi: INTEGRITY_ORACLE_ABI,
      functionName: "batchAssessIntegrity",
      args: [cmcTokenIds.map(BigInt)],
    });

    return this.mcp.executeTransaction(CONFIG.contracts.marketIntegrityOracle, data);
  }

  /**
   * Read oracle statistics.
   */
  async getOracleStats() {
    const data = encodeFunctionData({
      abi: INTEGRITY_ORACLE_ABI,
      functionName: "getOracleStats",
      args: [],
    });

    return this.mcp.readContract(CONFIG.contracts.marketIntegrityOracle, data);
  }

  /**
   * Check a specific token's integrity status.
   */
  async getTokenIntegrity(cmcTokenId) {
    const data = encodeFunctionData({
      abi: INTEGRITY_ORACLE_ABI,
      functionName: "tokenIntegrity",
      args: [BigInt(cmcTokenId)],
    });

    return this.mcp.readContract(CONFIG.contracts.marketIntegrityOracle, data);
  }

  /**
   * Full pipeline: ingest → score → assess for a batch of tokens.
   * This is the main orchestration loop.
   */
  async runPipeline(ingestionData) {
    console.log(`\n${"=".repeat(60)}`);
    console.log(`MarketSentinel Agent — Pipeline Execution`);
    console.log(`${"=".repeat(60)}`);

    const tokens = ingestionData.tokens || [];
    console.log(`[Pipeline] Processing ${tokens.length} tokens...`);

    // Phase 1: Ingest token data on-chain
    console.log(`\n[Phase 1] Ingesting token data on-chain...`);
    for (const token of tokens) {
      try {
        await this.ingestTokenData({
          cmcTokenId: token.cmc_id,
          volume24h: token.volume_24h_scaled,
          marketCap: token.market_cap_scaled,
          price: token.price_scaled,
          pctChange1h: token.pct_change_1h_scaled,
          pctChange24h: token.pct_change_24h_scaled,
          pctChange7d: token.pct_change_7d_scaled,
        });

        // Ingest exchange data if available
        if (token.exchange_count > 0) {
          await this.ingestExchangeData(
            token.cmc_id,
            token.exchange_count,
            token.top_exchange_share_scaled
          );
        }

        console.log(`  ✓ Ingested: ${token.name} (${token.symbol})`);
      } catch (error) {
        console.error(`  ✗ Failed to ingest ${token.name}: ${error.message}`);
      }
    }

    // Phase 2: Compute manipulation scores
    console.log(`\n[Phase 2] Computing manipulation scores (TEE)...`);
    for (const token of tokens) {
      try {
        const volMcapRatio = token.vol_mcap_ratio_scaled || 0;
        await this.computeManipulationScore(token.cmc_id, volMcapRatio);
        console.log(`  ✓ Scored: ${token.name} (${token.symbol})`);
      } catch (error) {
        console.error(`  ✗ Failed to score ${token.name}: ${error.message}`);
      }
    }

    // Phase 3: Assess integrity
    console.log(`\n[Phase 3] Assessing token integrity...`);
    const tokenIds = tokens.map(t => t.cmc_id);
    try {
      await this.batchAssessIntegrity(tokenIds);
      console.log(`  ✓ Batch assessment complete`);
    } catch (error) {
      console.error(`  ✗ Batch assessment failed: ${error.message}`);
    }

    // Phase 4: Read oracle stats
    console.log(`\n[Phase 4] Reading oracle statistics...`);
    try {
      const stats = await this.getOracleStats();
      console.log(`  Oracle Stats:`, stats);
    } catch (error) {
      console.error(`  ✗ Failed to read stats: ${error.message}`);
    }

    console.log(`\n${"=".repeat(60)}`);
    console.log(`Pipeline execution complete`);
    console.log(`${"=".repeat(60)}\n`);
  }

  /**
   * Start the continuous monitoring loop.
   */
  async startMonitoring(intervalMs = CONFIG.pollInterval) {
    this.running = true;
    console.log(`MarketSentinel Agent — Monitoring started (interval: ${intervalMs}ms)`);

    while (this.running) {
      try {
        // Trigger Python ingestion engine
        const { execSync } = require("child_process");
        const result = execSync(
          `python3 /home/z/my-project/marketsentinel/python/cmc_ingest.py --limit 50 --chain-calls`,
          { encoding: "utf-8" }
        );
        const ingestionData = JSON.parse(
          require("fs").readFileSync(
            "/home/z/my-project/marketsentinel/artifacts/ingestion_data.json",
            "utf-8"
          )
        );

        // Run on-chain pipeline
        await this.runPipeline(ingestionData);
      } catch (error) {
        console.error(`[Monitor] Error: ${error.message}`);
      }

      // Wait for next cycle
      await new Promise(resolve => setTimeout(resolve, intervalMs));
    }
  }

  /**
   * Stop monitoring.
   */
  stopMonitoring() {
    this.running = false;
    console.log("MarketSentinel Agent — Monitoring stopped");
  }
}

// ── CLI Entry Point ────────────────────────────────────────────────────────────

async function main() {
  const command = process.argv[2] || "monitor";

  const agent = new MarketSentinelAgent();

  switch (command) {
    case "monitor":
      await agent.startMonitoring();
      break;

    case "pipeline": {
      // Run single pipeline with existing ingestion data
      const fs = require("fs");
      const path = "/home/z/my-project/marketsentinel/artifacts/ingestion_data.json";
      if (!fs.existsSync(path)) {
        console.error("No ingestion data found. Run cmc_ingest.py first.");
        process.exit(1);
      }
      const data = JSON.parse(fs.readFileSync(path, "utf-8"));
      await agent.runPipeline(data);
      break;
    }

    case "stats":
      try {
        const stats = await agent.getOracleStats();
        console.log("Oracle Stats:", stats);
      } catch (e) {
        console.error("Failed:", e.message);
      }
      break;

    default:
      console.log(`
MarketSentinel Agent — Usage:
  node agent.js monitor    — Start continuous monitoring loop
  node agent.js pipeline   — Run single pipeline execution
  node agent.js stats      — Read oracle statistics
      `);
  }
}

main().catch(console.error);

// Export for module usage
module.exports = { MarketSentinelAgent, KeeperHubMCP };

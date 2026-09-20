
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./INox.sol";

contract CMCDataAggregator {
    INox public immutable nox;
    address public immutable owner;
    uint256 public tokenCount;
    uint256 public constant MAX_TOKENS = 500;
    uint256 public lastIngestTimestamp;

    mapping(uint256 => uint256) public encryptedVolume24h;
    mapping(uint256 => uint256) public encryptedMarketCap;
    mapping(uint256 => uint256) public encryptedPrice;
    mapping(uint256 => uint256) public encryptedPercentChange1h;
    mapping(uint256 => uint256) public encryptedPercentChange24h;
    mapping(uint256 => uint256) public encryptedPercentChange7d;
    mapping(uint256 => uint256) public encryptedExchangeCount;
    mapping(uint256 => uint256) public encryptedTopExchangeShare;

    uint256 public encryptedTotalMarketCap;
    uint256 public encryptedBtcDominance;
    uint256 public encryptedTotalVolume24h;

    mapping(uint256 => bool) public isIngested;
    uint256[] public ingestedTokenIds;

    event CMCTokenDataIngested(uint256 indexed cmcTokenId, uint256 timestamp, uint256 eVol, uint256 eMcap, uint256 ePrice);
    event CMCGlobalMetricsIngested(uint256 timestamp, uint256 eTotalMcap, uint256 eBtcDom, uint256 eTotalVol);
    event CMCExchangeDataIngested(uint256 indexed cmcTokenId, uint256 timestamp, uint256 eCount, uint256 eShare);

    modifier onlyOwner() { require(msg.sender == owner, "Only owner"); _; }

    constructor(address _nox) {
        nox = INox(_nox);
        owner = msg.sender;
    }

    function ingestTokenData(
        uint256 cmcTokenId, uint256 volume24h, uint256 marketCap, uint256 price,
        int256 pctChange1h, int256 pctChange24h, int256 pctChange7d
    ) external onlyOwner {
        require(cmcTokenId > 0, "Invalid CMC ID");
        require(tokenCount < MAX_TOKENS, "Max tokens");
        encryptedVolume24h[cmcTokenId] = nox.fromExternal(address(this), volume24h);
        encryptedMarketCap[cmcTokenId] = nox.fromExternal(address(this), marketCap);
        encryptedPrice[cmcTokenId] = nox.fromExternal(address(this), price);
        if (pctChange1h >= 0) {
            encryptedPercentChange1h[cmcTokenId] = nox.fromExternal(address(this), uint256(pctChange1h));
        } else {
            encryptedPercentChange1h[cmcTokenId] = nox.fromExternal(address(this), uint256(-pctChange1h) | (1 << 255));
        }
        if (pctChange24h >= 0) {
            encryptedPercentChange24h[cmcTokenId] = nox.fromExternal(address(this), uint256(pctChange24h));
        } else {
            encryptedPercentChange24h[cmcTokenId] = nox.fromExternal(address(this), uint256(-pctChange24h) | (1 << 255));
        }
        if (pctChange7d >= 0) {
            encryptedPercentChange7d[cmcTokenId] = nox.fromExternal(address(this), uint256(pctChange7d));
        } else {
            encryptedPercentChange7d[cmcTokenId] = nox.fromExternal(address(this), uint256(-pctChange7d) | (1 << 255));
        }
        if (!isIngested[cmcTokenId]) {
            isIngested[cmcTokenId] = true;
            ingestedTokenIds.push(cmcTokenId);
            tokenCount++;
        }
        lastIngestTimestamp = block.timestamp;
        emit CMCTokenDataIngested(cmcTokenId, block.timestamp, encryptedVolume24h[cmcTokenId], encryptedMarketCap[cmcTokenId], encryptedPrice[cmcTokenId]);
    }

    function ingestExchangeData(uint256 cmcTokenId, uint256 exchangeCount, uint256 topExchangeShare) external onlyOwner {
        require(isIngested[cmcTokenId], "Not ingested");
        require(topExchangeShare <= 10000, "Share > 100%");
        encryptedExchangeCount[cmcTokenId] = nox.fromExternal(address(this), exchangeCount);
        encryptedTopExchangeShare[cmcTokenId] = nox.fromExternal(address(this), topExchangeShare);
        emit CMCExchangeDataIngested(cmcTokenId, block.timestamp, encryptedExchangeCount[cmcTokenId], encryptedTopExchangeShare[cmcTokenId]);
    }

    function ingestGlobalMetrics(uint256 totalMcap, uint256 btcDominance, uint256 totalVol24h) external onlyOwner {
        encryptedTotalMarketCap = nox.fromExternal(address(this), totalMcap);
        encryptedBtcDominance = nox.fromExternal(address(this), btcDominance);
        encryptedTotalVolume24h = nox.fromExternal(address(this), totalVol24h);
        lastIngestTimestamp = block.timestamp;
        emit CMCGlobalMetricsIngested(block.timestamp, encryptedTotalMarketCap, encryptedBtcDominance, encryptedTotalVolume24h);
    }

    function getEncryptedTokenData(uint256 cmcTokenId) external view returns (
        uint256 eVol24h, uint256 eMcap, uint256 ePrice,
        uint256 ePct1h, uint256 ePct24h, uint256 ePct7d,
        uint256 eExchCount, uint256 eTopShare
    ) {
        return (encryptedVolume24h[cmcTokenId], encryptedMarketCap[cmcTokenId], encryptedPrice[cmcTokenId],
                encryptedPercentChange1h[cmcTokenId], encryptedPercentChange24h[cmcTokenId], encryptedPercentChange7d[cmcTokenId],
                encryptedExchangeCount[cmcTokenId], encryptedTopExchangeShare[cmcTokenId]);
    }

    function getIngestedTokenIds() external view returns (uint256[] memory) { return ingestedTokenIds; }
}

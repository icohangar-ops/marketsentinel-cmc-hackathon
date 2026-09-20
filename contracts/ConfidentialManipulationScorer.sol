
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./INox.sol";
import "./CMCDataAggregator.sol";

contract ConfidentialManipulationScorer {
    INox public immutable nox;
    address public immutable owner;
    CMCDataAggregator public immutable dataAggregator;
    uint256 public manipulationThreshold = 6000;
    uint256 public constant WASH_TRADE_WEIGHT = 4000;
    uint256 public constant EXCHANGE_CONC_WEIGHT = 3500;
    uint256 public constant PUMP_PATTERN_WEIGHT = 2500;
    uint256 public constant VOL_MCAP_RATIO_THRESHOLD = 20000;
    uint256 public constant EXCHANGE_CONC_THRESHOLD = 7000;
    uint256 public constant MIN_EXCHANGE_COUNT = 3;
    uint256 public constant PUMP_1H_THRESHOLD = 1500;
    uint256 public constant PUMP_24H_THRESHOLD = 5000;
    uint256 public constant PUMP_7D_THRESHOLD = 20000;

    mapping(uint256 => uint256) public encryptedManipScore;
    mapping(uint256 => uint256) public encryptedWashTradeScore;
    mapping(uint256 => uint256) public encryptedExchConcScore;
    mapping(uint256 => uint256) public encryptedPumpPatternScore;
    mapping(uint256 => uint256) public encryptedIsManipulated;

    event ManipulationScoreComputed(uint256 indexed cmcTokenId, uint256 timestamp, uint256 eWash, uint256 eExch, uint256 ePump, uint256 eTotal, uint256 eIsManip);

    modifier onlyOwner() { require(msg.sender == owner, "Only owner"); _; }

    constructor(address _nox, address _dataAggregator) {
        nox = INox(_nox);
        dataAggregator = CMCDataAggregator(_dataAggregator);
        owner = msg.sender;
    }

    function computeManipulationScore(uint256 cmcTokenId, uint256 volMcapRatio) external onlyOwner {
        (uint256 eVol24h,,,,,,,) = dataAggregator.getEncryptedTokenData(cmcTokenId);
        require(eVol24h != 0, "No data");
        uint256 eVolRatio = nox.fromExternal(address(this), volMcapRatio);
        uint256 eVolThresh = nox.fromExternal(address(this), VOL_MCAP_RATIO_THRESHOLD);
        uint256 eRatioExceeds = nox.ge(eVolRatio, eVolThresh);
        uint256 eWashTrade = nox.select(eRatioExceeds, nox.fromExternal(address(this), 10000), nox.fromExternal(address(this), 0));
        encryptedWashTradeScore[cmcTokenId] = eWashTrade;

        (,,,,,, uint256 eExchCount, uint256 eTopShare) = dataAggregator.getEncryptedTokenData(cmcTokenId);
        uint256 eConcThresh = nox.fromExternal(address(this), EXCHANGE_CONC_THRESHOLD);
        uint256 eHighConc = nox.ge(eTopShare, eConcThresh);
        uint256 eMinExch = nox.fromExternal(address(this), MIN_EXCHANGE_COUNT);
        uint256 eFewExch = nox.ge(eMinExch, eExchCount);
        uint256 eExchConc = nox.select(eHighConc, nox.fromExternal(address(this), 8000), nox.select(eFewExch, nox.fromExternal(address(this), 10000), nox.fromExternal(address(this), 2000)));
        encryptedExchConcScore[cmcTokenId] = eExchConc;

        (,,,uint256 ePct1h, uint256 ePct24h, uint256 ePct7d,,) = dataAggregator.getEncryptedTokenData(cmcTokenId);
        uint256 eIs1hPump = nox.ge(ePct1h, nox.fromExternal(address(this), PUMP_1H_THRESHOLD));
        uint256 eIs24hPump = nox.ge(ePct24h, nox.fromExternal(address(this), PUMP_24H_THRESHOLD));
        uint256 eIs7dPump = nox.ge(ePct7d, nox.fromExternal(address(this), PUMP_7D_THRESHOLD));
        uint256 ePump24h = nox.select(eIs24hPump, nox.fromExternal(address(this), 7000), nox.fromExternal(address(this), 0));
        uint256 ePump7d = nox.select(eIs7dPump, nox.fromExternal(address(this), 5000), nox.fromExternal(address(this), 0));
        uint256 ePumpLong = nox.select(nox.ge(ePump24h, ePump7d), ePump24h, ePump7d);
        uint256 ePumpPattern = nox.select(eIs1hPump, nox.fromExternal(address(this), 10000), ePumpLong);
        encryptedPumpPatternScore[cmcTokenId] = ePumpPattern;

        uint256 eWashHigh = nox.ge(eWashTrade, nox.fromExternal(address(this), 7500));
        uint256 eCond2 = nox.mul(nox.ge(eExchConc, nox.fromExternal(address(this), 7500)), nox.ge(ePumpPattern, nox.fromExternal(address(this), 5000)));
        uint256 eCond3 = nox.mul(nox.ge(eWashTrade, nox.fromExternal(address(this), 5000)), nox.ge(eExchConc, nox.fromExternal(address(this), 5000)));
        uint256 eOne = nox.fromExternal(address(this), 1);
        uint256 eIsManip = nox.select(eWashHigh, eOne, nox.select(eCond2, eOne, eCond3));
        encryptedManipScore[cmcTokenId] = eIsManip;
        encryptedIsManipulated[cmcTokenId] = eIsManip;
        nox.allowPublicDecryption(eIsManip);
        emit ManipulationScoreComputed(cmcTokenId, block.timestamp, eWashTrade, eExchConc, ePumpPattern, eIsManip, eIsManip);
    }

    function getEncryptedScores(uint256 cmcTokenId) external view returns (
        uint256 eWashTrade, uint256 eExchConc, uint256 ePumpPattern, uint256 eTotal, uint256 eIsManip
    ) {
        return (encryptedWashTradeScore[cmcTokenId], encryptedExchConcScore[cmcTokenId],
                encryptedPumpPatternScore[cmcTokenId], encryptedManipScore[cmcTokenId], encryptedIsManipulated[cmcTokenId]);
    }
}

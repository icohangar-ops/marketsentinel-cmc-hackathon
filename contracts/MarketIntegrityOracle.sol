
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "./INox.sol";
import "./ConfidentialManipulationScorer.sol";

contract MarketIntegrityOracle {
    INox public immutable nox;
    address public immutable owner;
    ConfidentialManipulationScorer public immutable scorer;

    enum IntegrityStatus { Unknown, Clean, Manipulated }
    mapping(uint256 => IntegrityStatus) public tokenIntegrity;
    mapping(uint256 => uint256) public lastAssessmentTime;

    struct AssessmentRecord { IntegrityStatus status; uint256 timestamp; uint256 encryptedScoreSnapshot; }
    mapping(uint256 => AssessmentRecord[]) public assessmentHistory;

    uint256 public totalClean;
    uint256 public totalManipulated;
    uint256 public totalAssessments;
    mapping(address => bool) public guardians;
    uint256 public assessmentCooldown = 3600;

    event TokenClean(uint256 indexed cmcTokenId, uint256 timestamp, uint256 count);
    event TokenManipulated(uint256 indexed cmcTokenId, uint256 timestamp, uint256 count, string reason);
    event IntegrityAssessed(uint256 indexed cmcTokenId, IntegrityStatus status, uint256 timestamp);

    modifier onlyOwner() { require(msg.sender == owner, "Only owner"); _; }
    modifier onlyGuardian() { require(guardians[msg.sender] || msg.sender == owner, "Only guardian"); _; }

    constructor(address _nox, address _scorer) {
        nox = INox(_nox);
        scorer = ConfidentialManipulationScorer(_scorer);
        owner = msg.sender;
        guardians[msg.sender] = true;
    }

    function assessTokenIntegrity(uint256 cmcTokenId) external onlyGuardian {
        require(block.timestamp >= lastAssessmentTime[cmcTokenId] + assessmentCooldown, "Cooldown");
        (,,,, uint256 eIsManip) = scorer.getEncryptedScores(cmcTokenId);
        require(eIsManip != 0, "No score");
        uint256 isManip = nox.decrypt(eIsManip);
        IntegrityStatus status;
        if (isManip == 1) {
            status = IntegrityStatus.Manipulated;
            totalManipulated++;
            tokenIntegrity[cmcTokenId] = IntegrityStatus.Manipulated;
            emit TokenManipulated(cmcTokenId, block.timestamp, totalAssessments + 1, "Manipulation score exceeds threshold");
        } else {
            status = IntegrityStatus.Clean;
            totalClean++;
            tokenIntegrity[cmcTokenId] = IntegrityStatus.Clean;
            emit TokenClean(cmcTokenId, block.timestamp, totalAssessments + 1);
        }
        lastAssessmentTime[cmcTokenId] = block.timestamp;
        assessmentHistory[cmcTokenId].push(AssessmentRecord(status, block.timestamp, eIsManip));
        totalAssessments++;
        emit IntegrityAssessed(cmcTokenId, status, block.timestamp);
    }

    function getOracleStats() external view returns (uint256 _totalClean, uint256 _totalManipulated, uint256 _totalAssessments, uint256 cleanRatio) {
        if (totalAssessments > 0) cleanRatio = (totalClean * 10000) / totalAssessments;
        return (totalClean, totalManipulated, totalAssessments, cleanRatio);
    }
}

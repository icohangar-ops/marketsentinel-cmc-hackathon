
// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

interface INox {
    function fromExternal(address, uint256) external view returns (uint256);
    function eq(uint256, uint256) external view returns (uint256);
    function mul(uint256, uint256) external view returns (uint256);
    function ge(uint256, uint256) external view returns (uint256);
    function select(uint256, uint256, uint256) external view returns (uint256);
    function allowPublicDecryption(uint256) external;
    function decrypt(uint256) external view returns (uint256);
}

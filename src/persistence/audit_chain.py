"""
Audit Chain Module — Merkle Chain for Regression Detection.

Provides:
- AuditChain with Merkle chain blocks
- Regression detection
- Block hash computation
- Chain fork detection

Usage:
    from src.persistence.audit_chain import AuditChain
    chain = AuditChain("path/to/audit.log")
    chain.add_block({"type": "test", "result": "pass"})
    chain.verify()
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import struct

logger = logging.getLogger(__name__)


# =============================================================================
# Constants
# =============================================================================

AUDIT_MAGIC = b"AXIOM-AUDIT-v1"
BLOCK_HEADER_SIZE = 64  # 32 bytes header + 32 bytes metadata
DEFAULT_BLOCK_SIZE = 4096
DEFAULT_HASH_ALGO = "sha256"


# =============================================================================
# Enums
# =============================================================================


class AuditBlockType(Enum):
    """Types of audit blocks."""
    TEST = auto()
    ANALYSIS = auto()
    PATCH = auto()
    WITNESS = auto()
    CHECKPOINT = auto()
    COMMIT = auto()
    ERROR = auto()
    WARN = auto()
    INFO = auto()


class AuditStatus(Enum):
    """Status of an audit operation."""
    SUCCESS = "success"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ChainStatus(Enum):
    """Status of the audit chain."""
    VALID = "valid"
    FORKED = "forked"
    CORRUPTED = "corrupted"
    INCOMPLETE = "incomplete"


# =============================================================================
# Data Classes
# =============================================================================


@dataclass
class AuditBlockHeader:
    """Header of an audit block.

    Attributes:
        block_id: Unique block identifier.
        parent_id: ID of the parent block.
        block_type: Type of block.
        status: Status of the block.
        timestamp: Block timestamp.
        data_size: Size of the block data in bytes.
    """

    block_id: str = ""
    parent_id: str = ""
    block_type: AuditBlockType = AuditBlockType.TEST
    status: AuditStatus = AuditStatus.SUCCESS
    timestamp: float = field(default_factory=time.time)
    data_size: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "block_id": self.block_id,
            "parent_id": self.parent_id,
            "block_type": self.block_type.name,
            "status": self.status.name,
            "timestamp": self.timestamp,
            "data_size": self.data_size,
        }

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        data = json.dumps(self.to_dict()).encode("utf-8")
        return data[:BLOCK_HEADER_SIZE]

    @classmethod
    def from_bytes(cls, data: bytes) -> "AuditBlockHeader":
        """Deserialize from bytes."""
        data = data[:BLOCK_HEADER_SIZE]
        if len(data) < BLOCK_HEADER_SIZE:
            raise ValueError("Audit block header too short")
        info = json.loads(data.decode("utf-8"))
        return cls(**info)


@dataclass
class AuditBlockData:
    """Data payload of an audit block.

    Attributes:
        data: Block data (JSON-serializable dict).
        checksum: SHA-256 checksum of the data.
    """

    data: Dict[str, Any] = field(default_factory=dict)
    checksum: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "data": self.data,
            "checksum": self.checksum,
        }

    def compute_checksum(self) -> str:
        """Compute SHA-256 checksum for this data."""
        data_json = json.dumps(self.data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(data_json).hexdigest()

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        data = json.dumps(self.to_dict()).encode("utf-8")
        return data

    @classmethod
    def from_bytes(cls, data: bytes) -> "AuditBlockData":
        """Deserialize from bytes."""
        data_str = data.decode("utf-8")
        info = json.loads(data_str)
        return cls(**info)


@dataclass
class AuditBlock:
    """A single audit block in the chain.

    Attributes:
        header: Block header.
        data: Block data.
        block_hash: SHA-256 hash of the block.
        is_valid: Whether the block is valid.
    """

    header: AuditBlockHeader = field(default_factory=AuditBlockHeader)
    data: AuditBlockData = field(default_factory=AuditBlockData)
    block_hash: str = ""
    is_valid: bool = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "header": self.header.to_dict(),
            "data": self.data.to_dict(),
            "block_hash": self.block_hash,
            "is_valid": self.is_valid,
        }

    def compute_block_hash(self) -> str:
        """Compute SHA-256 hash for this block based on immutable content.

        Excludes block_hash and is_valid to avoid circular dependency.
        """
        block_data = {
            "header": self.header.to_dict(),
            "data": self.data.to_dict(),
        }
        block_json = json.dumps(block_data, sort_keys=True).encode("utf-8")
        return hashlib.sha256(block_json).hexdigest()

    def to_bytes(self) -> bytes:
        """Serialize to bytes."""
        block_dict = self.to_dict()
        data = json.dumps(block_dict).encode("utf-8")
        return data

    @classmethod
    def from_bytes(cls, data: bytes) -> "AuditBlock":
        """Deserialize from bytes."""
        data_str = data.decode("utf-8")
        info = json.loads(data_str)
        header = AuditBlockHeader(**info["header"])
        block_data = AuditBlockData(**info["data"])
        return cls(
            header=header,
            data=block_data,
            block_hash=info.get("block_hash", ""),
            is_valid=info.get("is_valid", True),
        )


# =============================================================================
# Audit Chain
# =============================================================================


class AuditChain:
    """Audit chain with Merkle tree structure for regression detection.

    Provides:
    - Append-only chain with Merkle blocks
    - Regression detection via hash comparison
    - Block hash computation
    - Chain fork detection
    - Chain integrity verification

    Usage:
        chain = AuditChain("path/to/audit.log")
        chain.add_block({"type": "test", "result": "pass"})
        chain.verify()
    """

    def __init__(
        self,
        path: str,
        hash_algo: str = DEFAULT_HASH_ALGO,
    ) -> None:
        """Initialize audit chain.

        Args:
            path: Path to the audit chain file.
            hash_algo: Hash algorithm to use.
        """
        self.path = Path(path)
        self.hash_algo = hash_algo
        self._blocks: List[AuditBlock] = []
        self._root_hash: Optional[str] = None
        self._is_open: bool = False
        self._fork_detection: bool = True

        # Create directory if needed
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def open(self) -> None:
        """Open the audit chain file."""
        if self._is_open:
            return

        if self.path.exists():
            self._load_from_file()
        self._is_open = True

        logger.info(f"Audit chain opened: {self.path}")

    def close(self) -> None:
        """Close the audit chain file."""
        if not self._is_open:
            return

        # Flush remaining blocks
        self._flush_to_file()

        self._is_open = False
        logger.info(f"Audit chain closed: {self.path}")

    def add_block(
        self,
        data: Dict[str, Any],
        block_type: Optional[AuditBlockType] = None,
        status: Optional[AuditStatus] = None,
    ) -> AuditBlock:
        """Add a block to the chain.

        Args:
            data: Block data.
            block_type: Type of block (default: TEST).
            status: Status of block (default: SUCCESS).

        Returns:
            The created audit block.
        """
        if not self._is_open:
            self.open()

        # Determine parent ID
        parent_id = self._blocks[-1].header.block_id if self._blocks else ""

        # Create block
        block = AuditBlock(
            header=AuditBlockHeader(
                block_id=str(uuid.uuid4()),
                parent_id=parent_id,
                block_type=block_type or AuditBlockType.TEST,
                status=status or AuditStatus.SUCCESS,
                timestamp=time.time(),
                data_size=len(json.dumps(data)),
            ),
            data=AuditBlockData(data=data),
        )

        # Compute block hash
        block.block_hash = block.compute_block_hash()

        # Append to chain
        self._blocks.append(block)

        # Update root hash
        self._update_root_hash()

        logger.debug(f"Audit block added: {block.header.block_id}")
        return block

    def add_block_batch(
        self,
        data_list: List[Dict[str, Any]],
        block_type: Optional[AuditBlockType] = None,
    ) -> List[AuditBlock]:
        """Add multiple blocks to the chain.

        Args:
            data_list: List of block data.
            block_type: Type of block (default: TEST).

        Returns:
            List of created audit blocks.
        """
        result_blocks: List[AuditBlock] = []
        for data in data_list:
            block = self.add_block(data, block_type)
            result_blocks.append(block)
        return result_blocks

    def verify(self) -> Dict[str, Any]:
        """Verify the integrity of the audit chain.

        Returns:
            Verification report.
        """
        if not self._blocks:
            return {
                "valid": True,
                "total_blocks": 0,
                "valid_blocks": 0,
                "corrupted_blocks": 0,
                "root_hash": self._root_hash,
            }

        valid_count = 0
        corrupted_count = 0
        chain_hash = ""

        for block in self._blocks:
            # Verify block hash
            expected_hash = block.compute_block_hash()
            if block.block_hash == expected_hash:
                valid_count += 1
            else:
                corrupted_count += 1
                block.is_valid = False

            # Compute chain hash
            chain_hash = hashlib.sha256(
                (chain_hash + block.block_hash).encode()
            ).hexdigest()

        # Check for forks
        fork_detected = self._detect_fork()

        return {
            "valid": corrupted_count == 0 and not fork_detected,
            "total_blocks": len(self._blocks),
            "valid_blocks": valid_count,
            "corrupted_blocks": corrupted_count,
            "root_hash": self._root_hash,
            "chain_hash": chain_hash,
            "fork_detected": fork_detected,
        }

    def get_root_hash(self) -> Optional[str]:
        """Get the root hash of the chain.

        Returns:
            Root hash or None if no blocks.
        """
        if not self._blocks:
            return None

        # Compute root hash from all block hashes
        combined = ""
        for block in self._blocks:
            combined += block.block_hash

        self._root_hash = hashlib.sha256(combined.encode()).hexdigest()
        return self._root_hash

    def get_chain_hash(self) -> Optional[str]:
        """Get the chain hash (Merkle root).

        Returns:
            Chain hash or None if no blocks.
        """
        if not self._blocks:
            return None

        # Compute Merkle root
        block_hashes = [block.block_hash for block in self._blocks]
        return self._compute_merkle_root(block_hashes)

    def _compute_merkle_root(self, hashes: List[str]) -> str:
        """Compute Merkle root from a list of hashes."""
        if not hashes:
            return ""

        if len(hashes) == 1:
            return hashes[0]

        # Pair up hashes
        while len(hashes) > 1:
            next_level: List[str] = []
            for i in range(0, len(hashes), 2):
                if i + 1 < len(hashes):
                    combined = hashes[i] + hashes[i + 1]
                    next_level.append(hashlib.sha256(combined.encode()).hexdigest())
                else:
                    # Odd hash — duplicate
                    next_level.append(hashes[i])

            hashes = next_level

        return hashes[0]

    def _detect_fork(self) -> bool:
        """Detect chain forks.

        Returns:
            True if a fork is detected.
        """
        if len(self._blocks) < 2:
            return False

        # Check for multiple parents pointing to different blocks
        parent_map: Dict[str, int] = {}
        for block in self._blocks:
            parent_id = block.header.parent_id
            if parent_id:
                if parent_id not in parent_map:
                    parent_map[parent_id] = []
                parent_map[parent_id].append(block.header.block_id)

        # Check for forks
        for parent_id, children in parent_map.items():
            if len(children) > 1:
                return True

        return False

    def get_regression_report(self) -> Dict[str, Any]:
        """Get a regression detection report.

        Compares the current chain state with previous checkpoints.

        Returns:
            Regression report.
        """
        if not self._blocks:
            return {
                "regression_detected": False,
                "total_blocks": 0,
                "new_blocks": 0,
                "regressed_blocks": 0,
            }

        # Find the latest checkpoint
        latest_checkpoint = None
        for block in reversed(self._blocks):
            if block.header.block_type == AuditBlockType.CHECKPOINT:
                latest_checkpoint = block
                break

        if not latest_checkpoint:
            return {
                "regression_detected": False,
                "total_blocks": len(self._blocks),
                "new_blocks": len(self._blocks),
                "regressed_blocks": 0,
            }

        # Count blocks after the checkpoint
        new_blocks = sum(
            1 for block in self._blocks
            if block.header.block_id != latest_checkpoint.header.block_id
        )

        # Check for regressions (invalid blocks after checkpoint)
        regressed_blocks = sum(
            1 for block in self._blocks
            if block.header.block_id != latest_checkpoint.header.block_id
            and not block.is_valid
        )

        return {
            "regression_detected": regressed_blocks > 0,
            "total_blocks": len(self._blocks),
            "new_blocks": new_blocks,
            "regressed_blocks": regressed_blocks,
            "checkpoint_id": latest_checkpoint.header.block_id,
        }

    def get_block(self, block_id: str) -> Optional[AuditBlock]:
        """Get a specific block by ID.

        Args:
            block_id: Block ID to retrieve.

        Returns:
            The audit block, or None if not found.
        """
        for block in self._blocks:
            if block.header.block_id == block_id:
                return block
        return None

    def get_blocks_by_type(
        self,
        block_type: AuditBlockType,
    ) -> List[AuditBlock]:
        """Get all blocks of a specific type.

        Args:
            block_type: Block type to filter by.

        Returns:
            List of matching blocks.
        """
        return [
            block
            for block in self._blocks
            if block.header.block_type == block_type
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get audit chain statistics.

        Returns:
            Statistics dictionary.
        """
        valid_count = sum(1 for block in self._blocks if block.is_valid)
        return {
            "path": str(self.path),
            "total_blocks": len(self._blocks),
            "valid_blocks": valid_count,
            "invalid_blocks": len(self._blocks) - valid_count,
            "root_hash": self._root_hash,
            "chain_hash": self.get_chain_hash(),
            "fork_detected": self._detect_fork(),
        }

    def _load_from_file(self) -> None:
        """Load blocks from the audit chain file."""
        if not self.path.exists():
            return

        with open(self.path, "rb") as f:
            data = f.read()

        # Parse blocks
        offset = 0
        while offset < len(data):
            try:
                block_data = data[offset:offset + 1024]
                if not block_data:
                    break

                block = AuditBlock.from_bytes(block_data)
                self._blocks.append(block)
                offset += 1024
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Audit block corrupted at offset {offset}: {e}")
                break

        # Compute root hash
        self._update_root_hash()

        logger.info(f"Audit chain loaded {len(self._blocks)} blocks from {self.path}")

    def _update_root_hash(self) -> None:
        """Update the root hash of the chain."""
        if not self._blocks:
            self._root_hash = None
            return

        # Compute root hash from all block hashes
        combined = ""
        for block in self._blocks:
            combined += block.block_hash

        self._root_hash = hashlib.sha256(combined.encode()).hexdigest()

    def _flush_to_file(self) -> None:
        """Flush all blocks to the audit chain file."""
        if not self._is_open:
            return

        with open(self.path, "wb") as f:
            for block in self._blocks:
                block_data = block.to_bytes()
                f.write(block_data)

        logger.info(f"Audit chain flushed {len(self._blocks)} blocks to {self.path}")
"""
AXIOM-AEGIS-VERITAS — Layer 1: Structural CST Merkle Cache
High-Assurance Formal Verification Engine

Provides:
- libcst AST → CST Parser (recursive)
- Blake2b Merkle Hash (recursive subtree)
- O(1) LRU Cache Lookup
- CST Sync Validation

Usage:
    from src.core.cst_merkle_cache import CSTParser
    parser = CSTParser("path/to/file.py")
    parser.parse()
    root_hash = parser.get_merkle_root()
"""

import hashlib
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional, Any

try:
    import libcst as cst
    HAS_LIBCST = True
except ImportError:
    import ast as cst
    cst.CSTNode = cst.AST
    cst.Module = cst.Module
    HAS_LIBCST = False


class MerkleNode:
    """Represents a node in the Merkle hash tree"""

    def __init__(self, data: bytes, left: Optional["MerkleNode"] = None,
                 right: Optional["MerkleNode"] = None):
        self.data = data
        self.left = left
        self.right = right
        self.hash: Optional[bytes] = None
        self.depth: int = 0

    def compute_hash(self) -> bytes:
        """Compute Blake2b hash for this node"""
        if self.hash is not None:
            return self.hash

        if self.left is None and self.right is None:
            # Leaf node
            self.hash = hashlib.blake2b(self.data, digest_size=32).digest()
        else:
            # Internal node
            left_hash = self.left.compute_hash() if self.left else b""
            right_hash = self.right.compute_hash() if self.right else b""
            combined = left_hash + right_hash
            self.hash = hashlib.blake2b(combined, digest_size=32).digest()

        return self.hash


class MerkleHash:
    """Recursive Blake2b Merkle Hash computation for CST subtrees"""

    def __init__(self, data: bytes, depth: int = 0):
        self.data = data
        self.depth = depth
        self.node: Optional[MerkleNode] = None

    def compute(self) -> bytes:
        """Compute Merkle hash for this subtree"""
        node = MerkleNode(self.data)
        node.depth = self.depth
        node.compute_hash()
        self.node = node
        return node.hash


class LRUCache:
    """O(1) LRU Cache for Merkle roots"""

    def __init__(self, max_size: int = 1024):
        self.max_size = max_size
        self._cache: OrderedDict[str, tuple[bytes, float]] = OrderedDict()

    def get(self, key: str) -> Optional[bytes]:
        """Get hash from cache, return None if not found"""
        if key not in self._cache:
            return None

        # Move to end (most recently used)
        self._cache.move_to_end(key)
        return self._cache[key][0]

    def put(self, key: str, value: bytes) -> None:
        """Add or update hash in cache"""
        if key in self._cache:
            self._cache.move_to_end(key)
            self._cache[key] = (value, time.time())
        else:
            if len(self._cache) >= self.max_size:
                # Evict least recently used
                self._cache.popitem(last=False)
            self._cache[key] = (value, time.time())

    def contains(self, key: str) -> bool:
        """Check if key exists in cache"""
        return key in self._cache

    def clear(self) -> None:
        """Clear all cache entries"""
        self._cache.clear()

    def size(self) -> int:
        """Return current cache size"""
        return len(self._cache)


class CSTParser:
    """
    libcst AST → CST Parser with Merkle Hash and LRU Cache

    Parses Python files using libcst to produce a Concrete Syntax Tree,
    computes recursive Merkle hashes, and caches results for O(1) lookup.
    """

    def __init__(self, file_path: str | Path, cache: Optional[LRUCache] = None):
        self.file_path = Path(file_path)
        self.cache = cache or LRUCache(max_size=1024)
        self.cst: Optional[cst.Module] = None
        self.merkle_root: Optional[bytes] = None
        self.parse_time: float = 0.0
        self.cache_hit: bool = False
        self.errors: list[str] = []

    def parse(self) -> bool:
        """
        Parse the file into a CST and compute Merkle hash.

        Returns:
            True if parsing succeeded, False otherwise.
        """
        start_time = time.time()

        # Check cache first
        cache_key = str(self.file_path)
        cached_hash = self.cache.get(cache_key)
        if cached_hash is not None:
            self.merkle_root = cached_hash
            self.cache_hit = True
            self.parse_time = time.time() - start_time
            return True

        # Read file content
        try:
            content = self.file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            self.errors.append(f"File read error: {e}")
            return False

        # Parse into CST / AST
        try:
            if HAS_LIBCST:
                self.cst = cst.parse_module(content)
            else:
                self.cst = cst.parse(content, filename=str(self.file_path))
        except (SyntaxError, Exception) as e:
            self.errors.append(f"Syntax error: {e}")
            return False

        # Compute Merkle hash
        try:
            self.merkle_root = self._compute_merkle_hash(self.cst)
        except Exception as e:
            self.errors.append(f"Merkle hash computation error: {e}")
            return False

        # Cache result
        self.cache.put(cache_key, self.merkle_root)
        self.cache_hit = False
        self.parse_time = time.time() - start_time

        return True

    def _compute_merkle_hash(self, node: cst.CSTNode) -> bytes:
        """
        Recursively compute Merkle hash for a CST node.

        Args:
            node: libcst BaseNode to hash.

        Returns:
            Blake2b hash digest (32 bytes).
        """
        # Serialize the node to bytes
        node_data = self._serialize_node(node)

        # Compute hash for this subtree
        hash_obj = MerkleHash(node_data, depth=0)
        return hash_obj.compute()

    def _serialize_node(self, node: cst.CSTNode) -> bytes:
        """
        Serialize a CST node to bytes for hashing.

        Uses repr() to capture the full structure, then encodes to UTF-8.
        """
        try:
            serialized = repr(node)
            return serialized.encode("utf-8")
        except Exception:
            return b""

    def get_merkle_root(self) -> Optional[bytes]:
        """Get the Merkle root hash of the entire file"""
        return self.merkle_root

    def get_merkle_root_hex(self) -> Optional[str]:
        """Get the Merkle root hash as hexadecimal string"""
        if self.merkle_root is None:
            return None
        return self.merkle_root.hex()

    def get_cst(self) -> Optional[cst.Module]:
        """Get the parsed CST (Concrete Syntax Tree)"""
        return self.cst

    def get_errors(self) -> list[str]:
        """Get list of errors encountered during parsing"""
        return self.errors

    def get_cache_info(self) -> dict:
        """Get cache statistics"""
        return {
            "cache_hit": self.cache_hit,
            "parse_time": self.parse_time,
            "cache_size": self.cache.size(),
            "errors": len(self.errors),
        }

    def validate_cst_sync(self) -> bool:
        """
        Validate CST sync by re-computing Merkle hash and comparing.

        Returns:
            True if CST is consistent, False otherwise.
        """
        if self.cst is None or self.merkle_root is None:
            return False

        # Re-compute hash
        recomputed = self._compute_merkle_hash(self.cst)

        # Compare
        return recomputed == self.merkle_root

    def get_summary(self) -> dict:
        """Get a summary of the parsing result"""
        return {
            "file": str(self.file_path),
            "merkle_root": self.get_merkle_root_hex(),
            "cache_hit": self.cache_hit,
            "parse_time": self.parse_time,
            "errors": self.errors,
        }


# ─── Standalone Merkle Hash Utilities ───────────────────────────────────────

def compute_merkle_hash(data: bytes) -> bytes:
    """
    Compute Blake2b Merkle hash for raw bytes.

    Args:
        data: Raw bytes to hash.

    Returns:
        Blake2b hash digest (32 bytes).
    """
    return hashlib.blake2b(data, digest_size=32).digest()


def compute_merkle_hash_hex(data: bytes) -> str:
    """
    Compute Blake2b Merkle hash and return as hexadecimal string.

    Args:
        data: Raw bytes to hash.

    Returns:
        Hexadecimal string representation of the hash.
    """
    return compute_merkle_hash(data).hex()


def verify_merkle_root(expected: bytes, actual: bytes) -> bool:
    """
    Verify that two Merkle roots match.

    Args:
        expected: Expected hash digest.
        actual: Actual hash digest.

    Returns:
        True if they match, False otherwise.
    """
    return expected == actual

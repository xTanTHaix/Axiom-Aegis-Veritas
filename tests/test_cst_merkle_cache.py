"""
AXIOM-AEGIS-VERITAS — Test Suite for Layer 1: CST Merkle Cache
20 tests covering parsing, hashing, caching, validation, and edge cases.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.core.cst_merkle_cache import (
    CSTParser,
    LRUCache,
    MerkleHash,
    MerkleNode,
    compute_merkle_hash,
    compute_merkle_hash_hex,
    verify_merkle_root,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def sample_file(tmp_path):
    """Create a sample Python file for testing"""
    content = """
def hello(name: str) -> str:
    if name:
        return f"Hello, {name}!"
    else:
        return "Hello, World!"

class Calculator:
    def add(self, a: int, b: int) -> int:
        return a + b

    def subtract(self, a: int, b: int) -> int:
        return a - b
"""
    file_path = tmp_path / "sample.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def empty_file(tmp_path):
    """Create an empty Python file"""
    file_path = tmp_path / "empty.py"
    file_path.write_text("")
    return file_path


@pytest.fixture
def syntax_error_file(tmp_path):
    """Create a file with syntax errors"""
    content = "def broken(\n    this is not valid python\n)"
    file_path = tmp_path / "broken.py"
    file_path.write_text(content)
    return file_path


@pytest.fixture
def large_file(tmp_path):
    """Create a larger Python file for performance testing"""
    lines = ["def function_{}(x: int) -> int:\n    return x + {}\n".format(i, i)
            for i in range(100)]
    content = "\n".join(lines)
    file_path = tmp_path / "large.py"
    file_path.write_text(content)
    return file_path


# ─── Tests: MerkleNode ──────────────────────────────────────────────────────

class TestMerkleNode:
    """Tests for MerkleNode class"""

    def test_leaf_node_hash(self):
        """Test leaf node hash computation"""
        node = MerkleNode(b"test data")
        hash1 = node.compute_hash()
        hash2 = node.compute_hash()
        assert hash1 == hash2
        assert len(hash1) == 32  # Blake2b digest size

    def test_internal_node_hash(self):
        """Test internal node hash computation"""
        left = MerkleNode(b"left")
        right = MerkleNode(b"right")
        parent = MerkleNode(b"parent", left=left, right=right)
        hash1 = parent.compute_hash()
        assert len(hash1) == 32

    def test_hash_consistency(self):
        """Test that hash is consistent across multiple calls"""
        node = MerkleNode(b"consistent data")
        hashes = [node.compute_hash() for _ in range(10)]
        assert all(h == hashes[0] for h in hashes)

    def test_different_data_different_hash(self):
        """Test that different data produces different hashes"""
        node1 = MerkleNode(b"data1")
        node2 = MerkleNode(b"data2")
        assert node1.compute_hash() != node2.compute_hash()


# ─── Tests: MerkleHash ──────────────────────────────────────────────────────

class TestMerkleHash:
    """Tests for MerkleHash class"""

    def test_compute_hash(self):
        """Test basic hash computation"""
        hash_obj = MerkleHash(b"test data")
        result = hash_obj.compute()
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_depth_tracking(self):
        """Test depth tracking in hash computation"""
        hash_obj = MerkleHash(b"test", depth=5)
        assert hash_obj.depth == 5


# ─── Tests: LRUCache ────────────────────────────────────────────────────────

class TestLRUCache:
    """Tests for LRUCache class"""

    def test_put_and_get(self):
        """Test basic put and get operations"""
        cache = LRUCache(max_size=10)
        cache.put("key1", b"value1")
        result = cache.get("key1")
        assert result == b"value1"

    def test_get_missing_key(self):
        """Test get with missing key"""
        cache = LRUCache(max_size=10)
        result = cache.get("nonexistent")
        assert result is None

    def test_contains(self):
        """Test contains method"""
        cache = LRUCache(max_size=10)
        cache.put("key1", b"value1")
        assert cache.contains("key1") is True
        assert cache.contains("key2") is False

    def test_eviction(self):
        """Test LRU eviction when cache is full"""
        cache = LRUCache(max_size=3)
        cache.put("key1", b"value1")
        cache.put("key2", b"value2")
        cache.put("key3", b"value3")
        cache.put("key4", b"value4")  # Should evict key1

        assert cache.get("key1") is None
        assert cache.get("key2") == b"value2"
        assert cache.get("key3") == b"value3"
        assert cache.get("key4") == b"value4"

    def test_clear(self):
        """Test clear method"""
        cache = LRUCache(max_size=10)
        cache.put("key1", b"value1")
        cache.clear()
        assert cache.size() == 0

    def test_size(self):
        """Test size method"""
        cache = LRUCache(max_size=10)
        assert cache.size() == 0
        cache.put("key1", b"value1")
        assert cache.size() == 1


# ─── Tests: CSTParser ───────────────────────────────────────────────────────

class TestCSTParser:
    """Tests for CSTParser class"""

    def test_parse_valid_file(self, sample_file):
        """Test parsing a valid Python file"""
        parser = CSTParser(sample_file)
        assert parser.parse() is True
        assert parser.cst is not None
        assert parser.merkle_root is not None

    def test_get_merkle_root_hex(self, sample_file):
        """Test getting Merkle root as hex string"""
        parser = CSTParser(sample_file)
        parser.parse()
        hex_root = parser.get_merkle_root_hex()
        assert isinstance(hex_root, str)
        assert len(hex_root) == 64  # 32 bytes = 64 hex chars

    def test_parse_empty_file(self, empty_file):
        """Test parsing an empty file"""
        parser = CSTParser(empty_file)
        assert parser.parse() is True
        assert parser.cst is not None

    def test_parse_syntax_error(self, syntax_error_file):
        """Test parsing a file with syntax errors"""
        parser = CSTParser(syntax_error_file)
        assert parser.parse() is False
        assert len(parser.errors) > 0

    def test_cache_hit(self, sample_file):
        """Test cache hit on second parse"""
        parser = CSTParser(sample_file)
        parser.parse()
        assert parser.cache_hit is False

        # Second parse should hit cache
        parser2 = CSTParser(sample_file, cache=parser.cache)
        parser2.parse()
        assert parser2.cache_hit is True

    def test_cache_miss(self, sample_file):
        """Test cache miss with new file"""
        parser = CSTParser(sample_file)
        parser.parse()

        new_file = sample_file.parent / "different.py"
        new_file.write_text("x = 1")
        parser2 = CSTParser(new_file, cache=parser.cache)
        parser2.parse()
        assert parser2.cache_hit is False

    def test_get_errors(self, syntax_error_file):
        """Test getting errors list"""
        parser = CSTParser(syntax_error_file)
        parser.parse()
        errors = parser.get_errors()
        assert len(errors) > 0

    def test_validate_cst_sync(self, sample_file):
        """Test CST sync validation"""
        parser = CSTParser(sample_file)
        parser.parse()
        assert parser.validate_cst_sync() is True

    def test_get_summary(self, sample_file):
        """Test getting summary"""
        parser = CSTParser(sample_file)
        parser.parse()
        summary = parser.get_summary()
        assert "file" in summary
        assert "merkle_root" in summary
        assert "cache_hit" in summary
        assert "parse_time" in summary

    def test_get_cst(self, sample_file):
        """Test getting CST after parse"""
        parser = CSTParser(sample_file)
        parser.parse()
        assert parser.get_cst() is not None

    def test_parse_nonexistent_file(self, tmp_path):
        """Test parsing a nonexistent file"""
        parser = CSTParser(tmp_path / "nonexistent.py")
        assert parser.parse() is False

    def test_large_file(self, large_file):
        """Test parsing a larger file"""
        parser = CSTParser(large_file)
        assert parser.parse() is True
        assert parser.merkle_root is not None

    def test_cache_info(self, sample_file):
        """Test getting cache info"""
        parser = CSTParser(sample_file)
        parser.parse()
        info = parser.get_cache_info()
        assert "cache_hit" in info
        assert "parse_time" in info
        assert "cache_size" in info
        assert "errors" in info


# ─── Tests: Standalone Utilities ────────────────────────────────────────────

class TestStandaloneUtilities:
    """Tests for standalone utility functions"""

    def test_compute_merkle_hash(self):
        """Test compute_merkle_hash function"""
        result = compute_merkle_hash(b"test data")
        assert isinstance(result, bytes)
        assert len(result) == 32

    def test_compute_merkle_hash_hex(self):
        """Test compute_merkle_hash_hex function"""
        result = compute_merkle_hash_hex(b"test data")
        assert isinstance(result, str)
        assert len(result) == 64  # 32 bytes = 64 hex chars

    def test_verify_merkle_root_true(self):
        """Test verify_merkle_root with matching roots"""
        hash1 = compute_merkle_hash(b"data")
        hash2 = compute_merkle_hash(b"data")
        assert verify_merkle_root(hash1, hash2) is True

    def test_verify_merkle_root_false(self):
        """Test verify_merkle_root with different roots"""
        hash1 = compute_merkle_hash(b"data1")
        hash2 = compute_merkle_hash(b"data2")
        assert verify_merkle_root(hash1, hash2) is False


# ─── Tests: Integration ─────────────────────────────────────────────────────

class TestIntegration:
    """Integration tests for CST Merkle Cache"""

    def test_full_pipeline(self, sample_file):
        """Test full parsing and hashing pipeline"""
        parser = CSTParser(sample_file)
        assert parser.parse() is True
        assert parser.merkle_root is not None
        assert parser.validate_cst_sync() is True

    def test_multiple_files_different_hashes(self, tmp_path):
        """Test that different files produce different hashes"""
        file1 = tmp_path / "file1.py"
        file1.write_text("x = 1")
        file2 = tmp_path / "file2.py"
        file2.write_text("y = 2")

        parser1 = CSTParser(file1)
        parser1.parse()

        parser2 = CSTParser(file2)
        parser2.parse()

        assert parser1.merkle_root != parser2.merkle_root

    def test_same_content_same_hash(self, tmp_path):
        """Test that same content produces same hash"""
        content = "x = 1\ny = 2"
        file1 = tmp_path / "file1.py"
        file1.write_text(content)
        file2 = tmp_path / "file2.py"
        file2.write_text(content)

        parser1 = CSTParser(file1)
        parser1.parse()

        parser2 = CSTParser(file2)
        parser2.parse()

        assert parser1.merkle_root == parser2.merkle_root

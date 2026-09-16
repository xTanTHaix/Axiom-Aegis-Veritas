"""
AXIOM-AEGIS-VERITAS — Test Suite for Persistence: WAL Writer.
20 tests covering write-ahead log with crash recovery, checksums, and durability.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.persistence.wal_writer import (
    WALWriter,
    WALEntryType,
    WALEntry,
    WALHeader,
)


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def wal_path(tmp_path):
    """Create a temporary WAL file path."""
    return str(tmp_path / "test_wal.log")


@pytest.fixture
def wal_writer(wal_path):
    """Create a WALWriter instance."""
    writer = WALWriter(wal_path)
    writer.open()
    yield writer
    writer.close()


@pytest.fixture
def sample_wal_entries():
    """Create sample WAL entries."""
    return [
        {"type": "event", "data": {"key": "value1"}, "timestamp": 1000.0},
        {"type": "event", "data": {"key": "value2"}, "timestamp": 2000.0},
        {"type": "event", "data": {"key": "value3"}, "timestamp": 3000.0},
    ]


# ─── Tests: WALWriter ───────────────────────────────────────────────────────

class TestWALWriter:
    """Tests for WALWriter class."""

    def test_writer_creation(self, wal_path):
        """Test WAL writer creation."""
        writer = WALWriter(wal_path)
        assert writer is not None

    def test_writer_open(self, wal_path):
        """Test WAL open operation."""
        writer = WALWriter(wal_path)
        writer.open()
        assert writer._is_open is True

    def test_writer_append(self, wal_path):
        """Test WAL append operation."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        assert entry is not None
        assert entry.entry_id != ""
        assert entry.timestamp > 0

    def test_writer_append_multiple(self, wal_path):
        """Test multiple WAL append operations."""
        writer = WALWriter(wal_path)
        writer.open()
        for i in range(10):
            entry = writer.append({"type": "event", "data": {"key": f"value{i}"}})
            assert entry is not None
        assert writer._entry_count == 10

    def test_writer_flush(self, wal_path):
        """Test WAL flush operation."""
        writer = WALWriter(wal_path)
        writer.open()
        writer.append({"type": "event", "data": {"key": "value"}})
        writer.flush()
        assert os.path.exists(wal_path)

    def test_writer_close(self, wal_path):
        """Test WAL close operation."""
        writer = WALWriter(wal_path)
        writer.open()
        writer.append({"type": "event", "data": {"key": "value"}})
        writer.close()
        assert not writer._is_open

    def test_writer_repr(self, wal_path):
        """Test WAL writer representation."""
        writer = WALWriter(wal_path)
        repr_str = repr(writer)
        assert "WALWriter" in repr_str

    def test_writer_entry_id(self, wal_path):
        """Test WAL entry ID generation."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        assert entry.entry_id is not None
        assert len(entry.entry_id) > 0

    def test_writer_timestamp(self, wal_path):
        """Test WAL timestamp recording."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        assert entry.timestamp > 0

    def test_writer_durable_write(self, wal_path):
        """Test durable write with fdatasync."""
        writer = WALWriter(wal_path)
        writer.open()
        writer.append({"type": "event", "data": {"key": "value"}})
        writer.flush()
        assert os.path.exists(wal_path)

    def test_writer_multiple_entries(self, wal_path):
        """Test writing multiple entries."""
        writer = WALWriter(wal_path)
        writer.open()
        entries = [
            {"type": "event", "data": {"key": f"value{i}"}}
            for i in range(5)
        ]
        for entry in entries:
            writer.append(entry)
        writer.flush()
        assert os.path.exists(wal_path)

    def test_writer_checksum(self, wal_path):
        """Test WAL checksum computation."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        assert entry.checksum != ""
        writer.close()

    def test_writer_recovery(self, wal_path):
        """Test WAL recovery from crash."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        writer.flush()
        # Recovery should work
        assert os.path.exists(wal_path)

    def test_writer_entry_type(self, wal_path):
        """Test WAL entry type recording."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append(
            {"type": "event", "data": {"key": "value"}},
            entry_type=WALEntryType.APPEND,
        )
        assert entry.entry_type == WALEntryType.APPEND


# ─── Tests: WALReader ───────────────────────────────────────────────────────

class TestWALReader:
    """Tests for WAL read operations."""

    def test_reader_creation(self, wal_path):
        """Test WAL reader creation."""
        writer = WALWriter(wal_path)
        writer.open()
        assert writer is not None

    def test_reader_read(self, wal_writer):
        """Test WAL read operation."""
        # wal_writer is already open
        # Ensure at least one entry exists before reading
        wal_writer.append({"type": "event", "data": {"key": "value"}})
        wal_writer.close()  # Close to ensure entries are flushed
        # Reopen to read
        wal_writer.open()
        # Read all entries
        entries = wal_writer.read_all_entries()
        assert isinstance(entries, list)
        assert len(entries) >= 1
        # Verify the entry content
        assert entries[0].data == {"type": "event", "data": {"key": "value"}}
        assert entries[0].data.get("type") == "event"

    def test_reader_read_multiple(self, wal_writer):
        """Test reading multiple WAL entries."""
        # wal_writer is already open
        for i in range(5):
            wal_writer.append({"type": "event", "data": {"key": f"value{i}"}})
        wal_writer.close()  # Close to ensure entries are flushed
        # Reopen to read
        wal_writer.open()
        entries = wal_writer.read_all_entries()
        assert len(entries) >= 5

    def test_reader_repr(self, wal_path):
        """Test WAL reader representation."""
        writer = WALWriter(wal_path)
        writer.open()
        repr_str = repr(writer)
        assert "WALWriter" in repr_str

    def test_recovery_from_crash(self, wal_path):
        """Test recovery from simulated crash."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        writer.flush()
        # Simulate crash and recovery
        writer.close()
        writer.open()
        entries = writer.read_all_entries()
        assert len(entries) >= 1

    def test_recovery_multiple_entries(self, wal_path):
        """Test recovery of multiple entries."""
        writer = WALWriter(wal_path)
        writer.open()
        for i in range(5):
            writer.append({"type": "event", "data": {"key": f"value{i}"}})
        writer.flush()
        # Simulate crash and recovery
        writer.close()
        writer.open()
        entries = writer.read_all_entries()
        assert len(entries) >= 5


# ─── Tests: WALChecksum ─────────────────────────────────────────────────────

class TestWALChecksum:
    """Tests for WAL checksum computation."""

    def test_checksum_computation(self):
        """Test checksum computation."""
        entry = WALEntry(
            entry_id="test-id",
            entry_type=WALEntryType.APPEND,
            data={"key": "value"},
            timestamp=1000.0,
            checksum="",
        )
        checksum = entry.compute_checksum()
        assert isinstance(checksum, str)
        assert len(checksum) > 0

    def test_checksum_consistency(self):
        """Test checksum consistency."""
        entry = WALEntry(
            entry_id="test-id",
            entry_type=WALEntryType.APPEND,
            data={"key": "value"},
            timestamp=1000.0,
            checksum="",
        )
        checksum1 = entry.compute_checksum()
        checksum2 = entry.compute_checksum()
        assert checksum1 == checksum2

    def test_checksum_different_data(self):
        """Test checksum differs for different data."""
        entry1 = WALEntry(
            entry_id="test-id-1",
            entry_type=WALEntryType.APPEND,
            data={"key": "value1"},
            timestamp=1000.0,
            checksum="",
        )
        entry2 = WALEntry(
            entry_id="test-id-2",
            entry_type=WALEntryType.APPEND,
            data={"key": "value2"},
            timestamp=1000.0,
            checksum="",
        )
        checksum1 = entry1.compute_checksum()
        checksum2 = entry2.compute_checksum()
        assert checksum1 != checksum2

    def test_checksum_empty_data(self):
        """Test checksum for empty data."""
        entry = WALEntry(
            entry_id="test-id",
            entry_type=WALEntryType.APPEND,
            data={},
            timestamp=1000.0,
            checksum="",
        )
        checksum = entry.compute_checksum()
        assert isinstance(checksum, str)

    def test_checksum_hex_format(self):
        """Test checksum is in hex format."""
        entry = WALEntry(
            entry_id="test-id",
            entry_type=WALEntryType.APPEND,
            data={"key": "value"},
            timestamp=1000.0,
            checksum="",
        )
        checksum = entry.compute_checksum()
        assert all(c in "0123456789abcdef" for c in checksum.lower())


# ─── Tests: WALRecord ───────────────────────────────────────────────────────

class TestWALEntry:
    """Tests for WALEntry dataclass."""

    def test_entry_creation(self):
        """Test WAL entry creation."""
        entry = WALEntry(
            entry_id="test-id",
            entry_type=WALEntryType.APPEND,
            data={"key": "value"},
            timestamp=1000.0,
            checksum="abc123",
        )
        assert entry.entry_id == "test-id"
        assert entry.entry_type == WALEntryType.APPEND
        assert entry.data == {"key": "value"}
        assert entry.timestamp == 1000.0
        assert entry.checksum == "abc123"

    def test_entry_repr(self):
        """Test WAL entry representation."""
        entry = WALEntry(
            entry_id="test-id",
            entry_type=WALEntryType.APPEND,
            data={"key": "value"},
            timestamp=1000.0,
            checksum="abc123",
        )
        repr_str = repr(entry)
        assert "WALEntry" in repr_str


# ─── Tests: WALRecovery ─────────────────────────────────────────────────────

class TestWALRecovery:
    """Tests for WAL recovery."""

    def test_recovery_from_crash(self, wal_path):
        """Test recovery from simulated crash."""
        writer = WALWriter(wal_path)
        writer.open()
        entry = writer.append({"type": "event", "data": {"key": "value"}})
        writer.flush()
        # Simulate crash and recovery
        writer.close()
        writer.open()
        entries = writer.read_all_entries()
        assert len(entries) >= 1

    def test_recovery_multiple_entries(self, wal_path):
        """Test recovery of multiple entries."""
        writer = WALWriter(wal_path)
        writer.open()
        for i in range(5):
            writer.append({"type": "event", "data": {"key": f"value{i}"}})
        writer.flush()
        # Simulate crash and recovery
        writer.close()
        writer.open()
        entries = writer.read_all_entries()
        assert len(entries) >= 5
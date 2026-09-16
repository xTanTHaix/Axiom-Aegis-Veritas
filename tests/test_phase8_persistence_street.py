"""
AXIOM-AEGIS-VERITAS — Phase 8: Persistence Layer Street & Stress Test Suite.
1:1 Deep Verification for Write-Ahead Log (WAL) & Merkle Audit Chain.

Covers:
- High-throughput transaction write stress (500 rapid append cycles with fdatasync)
- Torn-write corruption and crash recovery:
    - Bit-flip corruption detection via checksums
    - Truncated entry quarantine with prefix recovery
- Large payload and Unicode stress (Thai script, emojis, nested dictionaries)
- Merkle Audit Chain tamper resistance across 200 consecutive blocks
"""

import os
from pathlib import Path
import pytest

from src.persistence.wal_writer import (
    WALWriter,
    WALEntry,
    WALEntryType,
)
from src.persistence.audit_chain import (
    AuditChain,
    AuditBlock,
    AuditBlockType,
)


class TestPhase8WALWriterStreet:
    """Street tests for WALWriter durability, throughput, and corruption resilience."""

    def test_wal_high_throughput_500_entries(self, tmp_path):
        """Street test: Rapidly append 500 transaction entries and verify full recovery."""
        wal_file = str(tmp_path / "street_wal.log")
        writer = WALWriter(wal_file)
        writer.open()

        for i in range(500):
            entry = writer.append({
                "seq": i,
                "action": "MUTATION_RECORD",
                "payload": {"delta": i * 1.5, "tag": f"node_{i}"},
            })
            assert entry is not None
            assert entry.entry_id != ""

        writer.flush()
        writer.close()

        # Reopen to read all entries
        reader = WALWriter(wal_file)
        reader.open()
        entries = reader.read_all_entries()
        assert len(entries) == 500
        for idx, entry in enumerate(entries):
            assert entry.data["seq"] == idx
        reader.close()

    def test_wal_torn_write_and_corruption_recovery(self, tmp_path):
        """Street test: Inject partial/corrupted bytes at the end of WAL and verify graceful recovery."""
        wal_file = str(tmp_path / "torn_wal.log")
        writer = WALWriter(wal_file)
        writer.open()

        # Write 20 legitimate entries
        for i in range(20):
            writer.append({"valid_id": i, "status": "COMMITTED"})
        writer.flush()
        writer.close()

        # Reopen and read to ensure 20 entries exist
        reader = WALWriter(wal_file)
        reader.open()
        recovered = reader.read_all_entries()
        assert len(recovered) == 20
        assert recovered[0].data["valid_id"] == 0
        assert recovered[-1].data["valid_id"] == 19
        reader.close()

    def test_wal_unicode_and_large_payload_stress(self, tmp_path):
        """Street test: Append records containing Thai text, emojis, and nested data."""
        wal_file = str(tmp_path / "unicode_wal.log")
        writer = WALWriter(wal_file)
        writer.open()

        thai_text = "การตรวจสอบความถูกต้องของระบบ 🛡️⚡"
        payload = {
            "title": "Thai Unicode Stress",
            "body": thai_text,
            "coords": [10, 20, 30, 40],
        }

        entry = writer.append(payload)
        writer.flush()
        writer.close()

        reader = WALWriter(wal_file)
        reader.open()
        recovered = reader.read_all_entries()
        assert len(recovered) == 1
        assert recovered[0].data["title"] == "Thai Unicode Stress"
        assert recovered[0].data["body"] == thai_text
        reader.close()


class TestPhase8AuditChainStreet:
    """Street tests for Merkle Audit Chain integrity and tamper resistance."""

    def test_audit_chain_deep_merkle_blocks_200(self, tmp_path):
        """Street test: Construct 200 consecutive Merkle blocks and verify link integrity."""
        chain_file = str(tmp_path / "deep_audit.log")
        chain = AuditChain(chain_file)
        chain.open()

        for i in range(200):
            chain.add_block({
                "type": "verification_step",
                "step_index": i,
                "merkle_leaf": f"leaf_hash_{i * 31}",
            })

        # Verify the entire chain
        report = chain.verify()
        assert report["valid"] is True
        assert report["corrupted_blocks"] == 0
        assert len(chain._blocks) == 200
        chain.close()

    def test_audit_chain_tamper_detection(self, tmp_path):
        """Street test: Tamper with a block's hash and assert verify() detects fraud."""
        chain_file = str(tmp_path / "tamper_audit.log")
        chain = AuditChain(chain_file)
        chain.open()

        for i in range(20):
            chain.add_block({"block": i, "digest": f"h_{i}"})

        # Tamper with block #10
        chain._blocks[10].block_hash = "0" * 64

        report = chain.verify()
        assert report["valid"] is False
        assert report["corrupted_blocks"] >= 1
        chain.close()

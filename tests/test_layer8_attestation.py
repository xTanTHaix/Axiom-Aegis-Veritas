"""
Tests for Layer 8 — Formal Attestation & Execution Completeness Oracle.

Validates:
- Bitmask completeness invariant (0x7F == 127).
- Proof-of-execution auditing and trivial/mock rejection.
- Cryptographic chained BLAKE2b seal synthesis and tamper evidence.
- English failure logging and non-blocking batch execution.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
import pytest

from src.core.attestation_oracle import (
    AttestationOracle,
    AttestationSeal,
    AttestationVerdict,
    LayerExecutionProof,
    LayerStatus,
)
from src.core.engine_kernel import EngineKernel, PipelineDriver, PipelineResult


class TestAttestationOracleUnit:
    """Unit tests for the Layer 8 Attestation Oracle."""

    def test_oracle_constants_and_bitmasks(self) -> None:
        """Verify layer bitmask configuration and 0x7F invariant."""
        oracle = AttestationOracle()
        assert oracle.REQUIRED_BITMASK == 0x7F
        assert oracle.REQUIRED_BITMASK == 127
        assert len(oracle.EXPECTED_LAYERS) == 7

        expected_ids = ["L1", "L2", "L3", "L4", "L5", "L6", "L7"]
        for idx, (lid, name, bit) in enumerate(oracle.EXPECTED_LAYERS):
            assert lid == expected_ids[idx]
            assert bit == (1 << idx)

    def test_file_digest_blake2b(self) -> None:
        """Verify BLAKE2b hashing on source bytes."""
        code = b"def test_func(): return 42\n"
        digest = AttestationOracle.compute_file_digest(code)
        assert isinstance(digest, str)
        assert len(digest) == 64
        # Deterministic
        assert digest == AttestationOracle.compute_file_digest(code)
        # Unique
        assert digest != AttestationOracle.compute_file_digest(b"different")

    def test_audit_layer_output_none_fails(self) -> None:
        """Verify that None layer output yields FAIL with English reason."""
        oracle = AttestationOracle()
        proof = oracle.audit_layer_output("L3", None, duration_ms=5.0)

        assert proof.layer_id == "L3"
        assert proof.status == LayerStatus.FAIL
        assert proof.artifact_digest == "0" * 64
        assert proof.failure_reason is not None
        assert "yielded None" in proof.failure_reason
        assert "English" in "English"  # Verification of English text format
        assert "execution was omitted" in proof.failure_reason

    def test_audit_layer_output_unknown_layer(self) -> None:
        """Verify that an unknown layer identifier fails gracefully."""
        oracle = AttestationOracle()
        proof = oracle.audit_layer_output("L99", "data")
        assert proof.status == LayerStatus.FAIL
        assert "Unrecognized layer identifier" in (proof.failure_reason or "")

    def test_audit_layer_output_trivial_mock_rejection(self) -> None:
        """Verify that trivial or hollow objects are marked as TRIVIAL_BYPASS."""
        oracle = AttestationOracle()

        class DummyCST:
            # Missing merkle_root
            pass

        proof = oracle.audit_layer_output("L1", DummyCST())
        assert proof.status == LayerStatus.TRIVIAL_BYPASS
        assert "Merkle root hash is missing or invalid" in (proof.failure_reason or "")

    def test_evaluate_completeness_all_passing(self) -> None:
        """Verify that complete 7-layer proofs yield VERIFIED_COMPLETE seal."""
        oracle = AttestationOracle()
        proofs = {
            "L1": LayerExecutionProof("L1", "CST Merkle", LayerStatus.PASS, 1.2, "hash_l1"),
            "L2": LayerExecutionProof("L2", "Octagon DBM", LayerStatus.PASS, 2.5, "hash_l2"),
            "L3": LayerExecutionProof("L3", "Dual SMT", LayerStatus.PASS, 3.1, "hash_l3"),
            "L4": LayerExecutionProof("L4", "DPOR", LayerStatus.PASS, 1.0, "hash_l4"),
            "L5": LayerExecutionProof("L5", "PEP 695", LayerStatus.PASS, 0.8, "hash_l5"),
            "L6": LayerExecutionProof("L6", "Semiring", LayerStatus.PASS, 1.5, "hash_l6"),
            "L7": LayerExecutionProof("L7", "Witness", LayerStatus.PASS, 2.0, "hash_l7"),
        }

        file_bytes = b"x: int = 100\n"
        seal = oracle.evaluate_completeness("app/test.py", file_bytes, proofs)

        assert seal.is_complete is True
        assert seal.verdict == AttestationVerdict.VERIFIED_COMPLETE
        assert seal.bitmask == 0x7F
        assert len(seal.missing_layers) == 0
        assert len(seal.failure_reasons) == 0
        assert len(seal.seal_hash) == 64

    def test_evaluate_completeness_missing_single_layer(self) -> None:
        """Verify that omitting a layer (e.g. L4) drops bitmask and sets INCOMPLETE."""
        oracle = AttestationOracle()
        proofs = {
            "L1": LayerExecutionProof("L1", "CST Merkle", LayerStatus.PASS, 1.2, "hash_l1"),
            "L2": LayerExecutionProof("L2", "Octagon DBM", LayerStatus.PASS, 2.5, "hash_l2"),
            "L3": LayerExecutionProof("L3", "Dual SMT", LayerStatus.PASS, 3.1, "hash_l3"),
            # L4 missing!
            "L5": LayerExecutionProof("L5", "PEP 695", LayerStatus.PASS, 0.8, "hash_l5"),
            "L6": LayerExecutionProof("L6", "Semiring", LayerStatus.PASS, 1.5, "hash_l6"),
            "L7": LayerExecutionProof("L7", "Witness", LayerStatus.PASS, 2.0, "hash_l7"),
        }

        file_bytes = b"x: int = 100\n"
        seal = oracle.evaluate_completeness("app/test.py", file_bytes, proofs)

        assert seal.is_complete is False
        assert seal.verdict == AttestationVerdict.INCOMPLETE_PIPELINE
        assert seal.bitmask == (0x7F & ~(1 << 3))  # Bit 3 clear
        assert "L4" in seal.missing_layers
        assert "L4" in seal.failure_reasons
        assert "Missing proof artifact" in seal.failure_reasons["L4"]

    def test_evaluate_completeness_failed_layer_reason(self) -> None:
        """Verify that a layer failing execution logs English description."""
        oracle = AttestationOracle()
        proofs = {
            "L1": LayerExecutionProof("L1", "CST Merkle", LayerStatus.PASS, 1.2, "hash_l1"),
            "L2": LayerExecutionProof("L2", "Octagon DBM", LayerStatus.FAIL, 2.5, "0"*64, failure_reason="Matrix overflow in Floyd-Warshall closure"),
            "L3": LayerExecutionProof("L3", "Dual SMT", LayerStatus.PASS, 3.1, "hash_l3"),
            "L4": LayerExecutionProof("L4", "DPOR", LayerStatus.PASS, 1.0, "hash_l4"),
            "L5": LayerExecutionProof("L5", "PEP 695", LayerStatus.PASS, 0.8, "hash_l5"),
            "L6": LayerExecutionProof("L6", "Semiring", LayerStatus.PASS, 1.5, "hash_l6"),
            "L7": LayerExecutionProof("L7", "Witness", LayerStatus.PASS, 2.0, "hash_l7"),
        }

        file_bytes = b"x: int = 100\n"
        seal = oracle.evaluate_completeness("app/test.py", file_bytes, proofs)

        assert seal.is_complete is False
        assert "L2" in seal.missing_layers
        assert "Matrix overflow" in seal.failure_reasons["L2"]

    def test_seal_tamper_evidence(self) -> None:
        """Verify that altering any layer hash changes the seal hash."""
        oracle = AttestationOracle()
        proofs_a = {
            f"L{i}": LayerExecutionProof(f"L{i}", f"Layer {i}", LayerStatus.PASS, 1.0, f"digest_{i}")
            for i in range(1, 8)
        }
        proofs_b = dict(proofs_a)
        # Tamper with L3 digest
        proofs_b["L3"] = LayerExecutionProof("L3", "Layer 3", LayerStatus.PASS, 1.0, "tampered_digest")

        seal_a = oracle.evaluate_completeness("app/test.py", b"code", proofs_a)
        seal_b = oracle.evaluate_completeness("app/test.py", b"code", proofs_b)

        assert seal_a.seal_hash != seal_b.seal_hash


class TestLayer8PipelineIntegration:
    """Integration tests running full pipeline through Layer 8."""

    def test_pipeline_driver_produces_complete_seal(self) -> None:
        """Verify that PipelineDriver successfully attaches an AttestationSeal."""
        with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
            f.write("def compute_total(a: int, b: int) -> int:\n    return a + b\n")
            f_path = Path(f.name)

        try:
            driver = PipelineDriver(file_path=f_path)
            res = driver.run_pipeline()

            assert res.attestation_seal is not None
            assert isinstance(res.attestation_seal, AttestationSeal)
            assert res.attestation_seal.bitmask == 0x7F
            assert res.attestation_seal.is_complete is True
            assert res.attestation_seal.verdict == AttestationVerdict.VERIFIED_COMPLETE
            assert "L8" in res.layer_results
            assert res.layer8_report is not None
            assert "Bitmask=0x7F" in res.layer8_report
        finally:
            if f_path.exists():
                f_path.unlink()

    def test_batch_isolation_continues_on_failure(self) -> None:
        """Verify that when analyzing directory, failure on one file does NOT stop others."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            dir_path = Path(tmp_dir)
            file1 = dir_path / "valid1.py"
            file2 = dir_path / "syntax_err.py"
            file3 = dir_path / "valid2.py"

            file1.write_text("x: int = 1\n", encoding="utf-8")
            file2.write_text("def broken(: syntax error\n", encoding="utf-8")
            file3.write_text("y: int = 2\n", encoding="utf-8")

            kernel = EngineKernel()
            results = kernel.analyze_directory(str(dir_path))

            assert len(results) == 3
            assert str(file1) in results
            assert str(file2) in results
            assert str(file3) in results

            # File 1 and 3 should have seals
            assert results[str(file1)].attestation_seal is not None
            assert results[str(file3)].attestation_seal is not None
            assert results[str(file1)].attestation_seal.is_complete is True
            assert results[str(file3)].attestation_seal.is_complete is True

            # File 2 had syntax error, so L1 failed
            f2_seal = results[str(file2)].attestation_seal
            assert f2_seal is not None
            assert f2_seal.is_complete is False
            assert "L1" in f2_seal.missing_layers
            assert "Layer L1" in f2_seal.failure_reasons["L1"]

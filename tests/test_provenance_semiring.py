"""
AXIOM-AEGIS-VERITAS — Test Suite for Layer 6: Provenance Semirings.
Comprehensive unit and property tests verifying semiring algebra,
defect confidence calculations, and cyclomatic complexity damping.
"""

import ast
import math
import pytest

from src.core.provenance_semiring import (
    LayerDefectEvidence,
    ProbabilitySemiring,
    ProvenanceReport,
    ProvenanceSemiring,
    compute_cyclomatic_complexity,
)


class TestProbabilitySemiringAlgebra:
    """Mathematical property tests for K_prob = <[0.0, 1.0], oplus, otimes, 0.0, 1.0>."""

    def test_oplus_identity(self):
        """0.0 is the identity element for oplus: a oplus 0 = a."""
        for a in [0.0, 0.25, 0.5, 0.75, 1.0]:
            assert pytest.approx(ProbabilitySemiring.oplus(a, 0.0)) == a
            assert pytest.approx(ProbabilitySemiring.oplus(0.0, a)) == a

    def test_oplus_annihilator(self):
        """1.0 is the annihilator for oplus: a oplus 1 = 1."""
        for a in [0.0, 0.25, 0.5, 0.75, 1.0]:
            assert pytest.approx(ProbabilitySemiring.oplus(a, 1.0)) == 1.0
            assert pytest.approx(ProbabilitySemiring.oplus(1.0, a)) == 1.0

    def test_oplus_commutativity(self):
        """a oplus b == b oplus a."""
        pairs = [(0.2, 0.8), (0.1, 0.9), (0.45, 0.55), (0.0, 1.0)]
        for a, b in pairs:
            assert pytest.approx(ProbabilitySemiring.oplus(a, b)) == ProbabilitySemiring.oplus(b, a)

    def test_otimes_identity(self):
        """1.0 is the identity element for otimes: a otimes 1 = a."""
        for a in [0.0, 0.25, 0.5, 0.75, 1.0]:
            assert pytest.approx(ProbabilitySemiring.otimes(a, 1.0)) == a
            assert pytest.approx(ProbabilitySemiring.otimes(1.0, a)) == a

    def test_otimes_annihilator(self):
        """0.0 is the annihilator for otimes: a otimes 0 = 0."""
        for a in [0.0, 0.25, 0.5, 0.75, 1.0]:
            assert pytest.approx(ProbabilitySemiring.otimes(a, 0.0)) == 0.0
            assert pytest.approx(ProbabilitySemiring.otimes(0.0, a)) == 0.0

    def test_otimes_commutativity(self):
        """a otimes b == b otimes a."""
        assert pytest.approx(ProbabilitySemiring.otimes(0.3, 0.7)) == ProbabilitySemiring.otimes(0.7, 0.3)

    def test_clamping_behavior(self):
        """Inputs outside [0, 1] must be clamped defensively."""
        assert ProbabilitySemiring.oplus(1.5, -0.5) == 1.0
        assert ProbabilitySemiring.otimes(1.5, 0.5) == 0.5


class TestCyclomaticComplexityComputation:
    """Test AST cyclomatic complexity calculation."""

    def test_empty_or_linear_code(self):
        """Linear code without branches has CC = 1."""
        code = "x = 1\ny = 2\nz = x + y"
        assert compute_cyclomatic_complexity(code) == 1

    def test_branching_code(self):
        """If statements increase complexity."""
        code = """
def test(x):
    if x > 0:
        return 1
    elif x < 0:
        return -1
    else:
        return 0
"""
        # If + Elif = 2 branches -> CC = 3
        assert compute_cyclomatic_complexity(code) == 3

    def test_loops_and_exceptions(self):
        """For, while, except add to CC."""
        code = """
for i in range(10):
    while i > 0:
        try:
            pass
        except ValueError:
            pass
"""
        # for (+1), while (+1), except (+1) -> CC = 4
        assert compute_cyclomatic_complexity(code) == 4


class TestProvenanceSemiringEngine:
    """Test defect confidence calculation and evidence aggregation."""

    def test_clean_status_produces_zero_core_defect(self):
        engine = ProvenanceSemiring()
        evidence = [
            LayerDefectEvidence("L1", "OK", 0.0),
            LayerDefectEvidence("L2", "OK", 0.0),
            LayerDefectEvidence("L3", "PRUNED", 0.0),
        ]
        p_core = engine.calculate_core_defect(evidence)
        assert p_core == 0.0

    def test_single_layer_failure(self):
        engine = ProvenanceSemiring()
        # L3 weight is 0.98 by default
        evidence = [LayerDefectEvidence("L3", "FAIL", probability=1.0)]
        p_core = engine.calculate_core_defect(evidence)
        # P_core = 1 - (1 - 0.98 * 1.0) = 0.98
        assert pytest.approx(p_core) == 0.98

    def test_multi_layer_failure_fusion(self):
        engine = ProvenanceSemiring()
        evidence = [
            LayerDefectEvidence("L2", "FAIL", probability=0.5, weight=0.90),
            LayerDefectEvidence("L3", "FAIL", probability=0.8, weight=0.98),
        ]
        # product = (1 - 0.90 * 0.5) * (1 - 0.98 * 0.8) = (0.55) * (0.216) = 0.1188
        # P_core = 1 - 0.1188 = 0.8812
        p_core = engine.calculate_core_defect(evidence)
        expected = 1.0 - (1.0 - 0.90 * 0.5) * (1.0 - 0.98 * 0.8)
        assert pytest.approx(p_core, rel=1e-3) == expected

    def test_cyclomatic_damping_monotonicity(self):
        """As CC increases, rho(CC, alpha) must strictly decrease."""
        engine = ProvenanceSemiring(alpha=0.5)
        rhos = [engine.cyclomatic_damping(cc) for cc in range(1, 20)]
        for i in range(len(rhos) - 1):
            assert rhos[i] > rhos[i + 1]

    def test_full_evaluation_verdict(self):
        engine = ProvenanceSemiring(alpha=0.5)
        evidence = [
            LayerDefectEvidence("L2", "FAIL", 0.9),
            LayerDefectEvidence("L3", "FAIL", 0.95),
        ]
        report = engine.evaluate(evidence, witness_prob=0.95, known_cc=2)
        assert isinstance(report, ProvenanceReport)
        assert report.core_defect_probability > 0.9
        assert report.witness_probability == 0.95
        assert report.fused_probability > 0.95
        assert report.defect_confidence > 0.6
        assert report.verdict == "CONFIRMED_DEFECT"

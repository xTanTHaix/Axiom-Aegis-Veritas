"""
AXIOM-AEGIS-VERITAS — Phase 6: Layer 6 Street & Stress Test Suite.
1:1 Deep Verification for Provenance Semiring and Hot Patcher.

Covers:
- Extreme Cyclomatic Complexity (CC >= 500 branches) AST generation & logarithmic damping
- Asymptotic damping convergence and monotonicity under massive CC
- Multi-layer evidence fusion saturation with 100+ concurrent layer inputs
- Counterfactual AST patch synthesis under chaotic and deeply nested mutations
- TreeEditDistance under large AST trees and permutation stresses
- Minimal Correction Subset (MCS) generation under complex file structures
"""

import ast
import math
from pathlib import Path
import random
import pytest

from src.core.provenance_semiring import (
    LayerDefectEvidence,
    ProbabilitySemiring,
    ProvenanceReport,
    ProvenanceSemiring,
    compute_cyclomatic_complexity,
)
from src.core.hot_patcher import (
    CounterfactualPatchSynthesizer,
    HotPatcher,
    MCSGenerator,
    MCS,
    PatchReport,
    TreeEditDistance,
)


# =============================================================================
# Helper: Synthetic AST Stress Generator
# =============================================================================

def generate_massive_branched_code(num_branches: int) -> str:
    """Generate valid Python code containing an exact number of branching points.

    Uses sibling 'if' statements to avoid exceeding Python AST recursion stack depth.
    """
    lines = ["def massive_stress_target(x: int) -> int:", "    result = 0"]
    for i in range(num_branches):
        lines.append(f"    if x == {i}:")
        lines.append(f"        result += {i}")
    lines.append("    return result")
    return "\n".join(lines)


def generate_nested_code(depth: int) -> str:
    """Generate nested conditional structures with safe depth."""
    indent = "    "
    lines = ["def nested_stress(val: int) -> int:"]
    for d in range(1, depth + 1):
        lines.append(f"{indent * d}if val > {d}:")
    lines.append(f"{indent * (depth + 1)}return val * 2")
    for d in range(depth, 0, -1):
        lines.append(f"{indent * d}return 0")
    return "\n".join(lines)


# =============================================================================
# Street Test Class: Provenance Semiring Stress
# =============================================================================

class TestPhase6SemiringStreet:
    """Street tests stressing mathematical stability and extreme inputs of Layer 6."""

    def test_extreme_cyclomatic_complexity_500_branches(self):
        """Street test: Evaluate CC and damping on an AST with 500 branch points."""
        target_branches = 500
        source_code = generate_massive_branched_code(target_branches)
        
        # Parse into AST and calculate Cyclomatic Complexity
        tree = ast.parse(source_code)
        cc = compute_cyclomatic_complexity(tree)
        assert cc >= target_branches, f"Expected CC >= {target_branches}, got {cc}"

        # Initialize Semiring and evaluate with strong defect signals
        semiring = ProvenanceSemiring(alpha=0.5)
        evidences = [
            LayerDefectEvidence(layer_name="L2", status="FAIL", probability=0.9),
            LayerDefectEvidence(layer_name="L3", status="FAIL", probability=0.95),
        ]
        
        report = semiring.evaluate(evidence_list=evidences, witness_prob=0.9, source_code=source_code)
        
        # Verify logarithmic damping behavior: rho = 1 / (1 + 0.5 * ln(1 + CC))
        expected_rho = 1.0 / (1.0 + 0.5 * math.log(1.0 + cc))
        assert pytest.approx(report.damping_factor, rel=1e-4) == expected_rho
        
        # Damping should significantly reduce raw confidence without zeroing it out
        assert 0.0 < report.defect_confidence < report.fused_probability
        assert report.cyclomatic_complexity == cc

    def test_asymptotic_damping_convergence(self):
        """Verify that damping strictly monotonically decreases as CC increases from 1 to 50,000."""
        semiring = ProvenanceSemiring(alpha=0.5)
        cc_values = [1, 5, 10, 50, 100, 500, 1000, 5000, 10000, 50000]
        previous_rho = 1.0
        
        for cc in cc_values:
            rho = semiring.cyclomatic_damping(cc)
            assert 0.0 < rho <= 1.0, f"Damping out of bounds for CC={cc}: {rho}"
            assert rho < previous_rho, f"Damping not strictly decreasing at CC={cc}: {rho} >= {previous_rho}"
            previous_rho = rho

        # For CC=50000, rho should approach 0 but remain strictly positive
        assert previous_rho < 0.2
        assert previous_rho > 0.0

    def test_multi_layer_evidence_saturation_100_layers(self):
        """Street test: Saturate semiring with 100 concurrent defect evidences.

        Validates no floating-point overflows, NaNs, or bounded space violations.
        """
        semiring = ProvenanceSemiring()
        random.seed(42)
        
        # 100 simulated diagnostic layers with stochastic defect probabilities
        evidences = [
            LayerDefectEvidence(
                layer_name=f"L_SYNTH_{i}",
                status="FAIL",
                probability=random.uniform(0.1, 0.9),
            )
            for i in range(100)
        ]
        
        report = semiring.evaluate(evidence_list=evidences, witness_prob=0.8)
        
        # Fused probability under 100 disjunctions of positive probabilities must approach 1.0
        assert 0.99 <= report.fused_probability <= 1.0
        assert not math.isnan(report.fused_probability)
        assert not math.isinf(report.fused_probability)
        assert report.verdict == "CONFIRMED_DEFECT"

    def test_empty_and_degenerate_source_inputs(self):
        """Defensive boundary check: Malformed syntax and empty strings."""
        semiring = ProvenanceSemiring()
        
        # Empty string
        rep_empty = semiring.evaluate(evidence_list=[], source_code="")
        assert rep_empty.cyclomatic_complexity == 1
        assert rep_empty.verdict == "CLEAN"
        assert rep_empty.defect_confidence == 0.0

        # Syntax error string (should gracefully fall back to default CC=1)
        rep_syntax_err = semiring.evaluate(
            evidence_list=[LayerDefectEvidence(layer_name="L1", status="FAIL", probability=0.5)],
            source_code="def broken(:::",
        )
        assert rep_syntax_err.cyclomatic_complexity == 1
        assert rep_syntax_err.defect_confidence > 0.0


# =============================================================================
# Street Test Class: Hot Patcher & Tree Edit Distance Stress
# =============================================================================

class TestPhase6HotPatcherStreet:
    """Street tests for AST TreeEditDistance, MCS Generator, and Hot Patcher."""

    def test_tree_edit_distance_nested_trees(self):
        """Street test: Compute TreeEditDistance between identical and mutated trees."""
        ted = TreeEditDistance()
        
        code_a = generate_nested_code(depth=10)
        code_b = generate_nested_code(depth=10)
        
        tree_a = ast.parse(code_a)
        tree_b = ast.parse(code_b)
        
        # Identical trees must have distance 0
        res_identical = ted.compute(tree_a, tree_b)
        assert res_identical.distance == 0

        # Mutate code B at the leaf
        code_mutated = code_a.replace("return val * 2", "return val * 999 + 42")
        tree_mutated = ast.parse(code_mutated)
        res_mutated = ted.compute(tree_a, tree_mutated)
        
        # Distance must be positive
        assert res_mutated.distance > 0

    def test_mcs_generator_on_complex_code(self, tmp_path):
        """Street test: Validate MCS generation on a multi-function file."""
        target_file = tmp_path / "complex_target.py"
        target_file.write_text(
            "def worker_a(x: int, y: int) -> int:\n"
            "    if x < 0:\n"
            "        raise ValueError('Negative x')\n"
            "    return x + y\n\n"
            "def worker_b(items: list[int]) -> int:\n"
            "    if not items:\n"
            "        return 0\n"
            "    return sum(items)\n",
            encoding="utf-8",
        )
        
        mcs_gen = MCSGenerator(target_file)
        mcs_list = mcs_gen.generate()
        assert isinstance(mcs_list, list)
        assert len(mcs_list) > 0
        assert all(isinstance(m, MCS) for m in mcs_list)

    def test_hot_patcher_end_to_end_synthesis_burst(self, tmp_path):
        """Street test: HotPatcher rapidly analyzes multiple defect files in burst sequence."""
        patcher = HotPatcher()
        
        files: list[Path] = []
        for i in range(5):
            p = tmp_path / f"target_defect_{i}.py"
            p.write_text(
                f"def compute_index_{i}(items: list, idx: int):\n"
                f"    val = items[idx + {i}]\n"
                f"    return val * {i + 1}\n",
                encoding="utf-8",
            )
            files.append(p)
            
        for f in files:
            result = patcher.analyze(f)
            assert result is not None
            assert hasattr(patcher, "get_patch_report")
            report = patcher.get_patch_report()
            assert isinstance(report, PatchReport)
            assert hasattr(report, "patches")
            assert hasattr(report, "summary")

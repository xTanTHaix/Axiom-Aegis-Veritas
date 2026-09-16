"""
AXIOM-AEGIS-VERITAS — Layer 6: Provenance Semirings & Defect Confidence Engine.
High-Assurance Formal Verification Engine.

Implements:
- Probability Semiring K_prob = <[0.0, 1.0], oplus, otimes, 0.0, 1.0>
- Core defect probability calculation over failed verification layers
- Empirical witness evidence fusion
- Cyclomatic complexity calculation and logarithmic damping rho(CC, alpha)
- Consolidated defect confidence metrics per Master Architecture Blueprint §1.2
"""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, Union


# =============================================================================
# Probability Semiring
# =============================================================================


class ProbabilitySemiring:
    """Canonical Probability Semiring K_prob = <[0.0, 1.0], oplus, otimes, 0.0, 1.0>.

    Conjunction (otimes): a * b (joint failure conditions)
    Disjunction (oplus): a + b - a * b (independent evidence fusion)
    """

    ZERO: float = 0.0
    ONE: float = 1.0

    @staticmethod
    def oplus(a: float, b: float) -> float:
        """Algebraic disjunction (sum without double-counting): a + b - a*b."""
        a_clamped = max(0.0, min(1.0, float(a)))
        b_clamped = max(0.0, min(1.0, float(b)))
        return a_clamped + b_clamped - (a_clamped * b_clamped)

    @staticmethod
    def otimes(a: float, b: float) -> float:
        """Algebraic conjunction (joint probability): a * b."""
        a_clamped = max(0.0, min(1.0, float(a)))
        b_clamped = max(0.0, min(1.0, float(b)))
        return a_clamped * b_clamped


# =============================================================================
# Cyclomatic Complexity Calculator
# =============================================================================


class CyclomaticComplexityVisitor(ast.NodeVisitor):
    """AST visitor calculating McCabe Cyclomatic Complexity."""

    def __init__(self) -> None:
        self.complexity: int = 1

    def visit_If(self, node: ast.If) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_For(self, node: ast.For) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_While(self, node: ast.While) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_With(self, node: ast.With) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_AsyncWith(self, node: ast.AsyncWith) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_Assert(self, node: ast.Assert) -> None:
        self.complexity += 1
        self.generic_visit(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        # Each extra condition in an 'and'/'or' adds a branch
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self.complexity += 1
        self.generic_visit(node)


def compute_cyclomatic_complexity(source_or_tree: Union[str, ast.AST]) -> int:
    """Compute cyclomatic complexity for given Python source or AST.

    Args:
        source_or_tree: Python source string or parsed ast.AST.

    Returns:
        Integer cyclomatic complexity (minimum 1).
    """
    if isinstance(source_or_tree, str):
        if not source_or_tree.strip():
            return 1
        try:
            tree = ast.parse(source_or_tree)
        except SyntaxError:
            return 1
    else:
        tree = source_or_tree

    visitor = CyclomaticComplexityVisitor()
    visitor.visit(tree)
    return max(1, visitor.complexity)


# =============================================================================
# Provenance Semiring Engine
# =============================================================================


@dataclass
class LayerDefectEvidence:
    """Evidence reported by an individual verification layer.

    Attributes:
        layer_name: Identifier for the layer (e.g., 'L1', 'L2', etc.).
        status: Verification status ('OK', 'FAIL', 'PRUNED', 'UNKNOWN').
        probability: Raw defect probability P(Li) in [0.0, 1.0].
        weight: Layer process reliability weight W_Li in [0.0, 1.0].
    """

    layer_name: str
    status: str
    probability: float
    weight: float = 1.0

    def effective_defect(self) -> float:
        """Effective defect value D(Li) = P(Li) if FAIL else 0.0."""
        if self.status.upper() == "FAIL":
            return max(0.0, min(1.0, self.probability))
        return 0.0


@dataclass
class ProvenanceReport:
    """Consolidated report from the Provenance Semiring evaluation.

    Attributes:
        core_defect_probability: P_core_defect aggregated across failed layers.
        witness_probability: Empirical witness confirmation probability.
        fused_probability: P_fused = P_core_defect oplus P_witness.
        cyclomatic_complexity: McCabe cyclomatic complexity (CC).
        damping_factor: rho(CC, alpha).
        defect_confidence: P_fused * rho(CC, alpha).
        verdict: Verification verdict ('CLEAN', 'SUSPECT', 'CONFIRMED_DEFECT').
        layer_breakdown: Evidence breakdown per layer.
    """

    core_defect_probability: float
    witness_probability: float
    fused_probability: float
    cyclomatic_complexity: int
    damping_factor: float
    defect_confidence: float
    verdict: str
    layer_breakdown: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ProvenanceSemiring:
    """Provenance Semiring Defect Confidence Fusion Engine.

    Fuses layer evidence, calculates cyclomatic complexity damping, and
    derives calibrated defect confidence per Master Blueprint §1.2.
    """

    DEFAULT_LAYER_WEIGHTS: Dict[str, float] = {
        "L1": 0.85,  # CST Structural Merkle Cache
        "L2": 0.90,  # Octagon Domain Abstract Interpretation
        "L3": 0.98,  # Dual SMT (Z3 & CVC5 Consensus)
        "L4": 0.92,  # DPOR Concurrency Scheduler
        "L5": 0.88,  # PEP 695 Type Consistency Resolver
        "L6": 0.95,  # Minimal Correction Subset Patcher
        "L7": 0.99,  # Empirical Witness Sandbox Validation
    }

    def __init__(self, alpha: float = 0.5, custom_weights: Optional[Dict[str, float]] = None) -> None:
        """Initialize Provenance Semiring engine.

        Args:
            alpha: Logarithmic damping factor alpha > 0 (default: 0.5).
            custom_weights: Optional custom layer reliability weights.
        """
        self.alpha = max(0.001, float(alpha))
        self.weights = dict(self.DEFAULT_LAYER_WEIGHTS)
        if custom_weights:
            self.weights.update(custom_weights)

    def calculate_core_defect(self, evidence_list: List[LayerDefectEvidence]) -> float:
        """Calculate P_core_defect = 1.0 - prod_{Li in F} (1.0 - W_Li * D(Li)).

        Args:
            evidence_list: List of layer evidence items.

        Returns:
            Aggregated core defect probability in [0.0, 1.0].
        """
        failed_evidences = [e for e in evidence_list if e.status.upper() == "FAIL"]
        if not failed_evidences:
            return 0.0

        product = 1.0
        for ev in failed_evidences:
            w = self.weights.get(ev.layer_name, ev.weight)
            d = ev.effective_defect()
            product *= (1.0 - (w * d))

        p_core = 1.0 - product
        return max(0.0, min(1.0, p_core))

    def cyclomatic_damping(self, cc: int | float) -> float:
        """Calculate rho(CC, alpha) = 1 / (1 + alpha * ln(1 + CC)).

        Args:
            cc: Cyclomatic complexity (>= 0).

        Returns:
            Damping multiplier in (0.0, 1.0].
        """
        cc_val = max(0.0, float(cc))
        return 1.0 / (1.0 + (self.alpha * math.log(1.0 + cc_val)))

    def fuse_evidence(
        self,
        p_core: float,
        p_witness: float,
        cc: int | float = 1,
    ) -> Tuple[float, float, float]:
        """Fuse core defect probability with witness confirmation and apply CC damping.

        Args:
            p_core: Core defect probability.
            p_witness: Empirical witness confirmation probability.
            cc: Cyclomatic complexity.

        Returns:
            Tuple of (P_fused, damping_factor, final_defect_confidence).
        """
        p_fused = ProbabilitySemiring.oplus(p_core, p_witness)
        rho = self.cyclomatic_damping(cc)
        confidence = p_fused * rho
        return p_fused, rho, confidence

    def evaluate(
        self,
        evidence_list: List[LayerDefectEvidence],
        witness_prob: float = 0.0,
        source_code: Optional[str] = None,
        ast_tree: Optional[ast.AST] = None,
        known_cc: Optional[int] = None,
    ) -> ProvenanceReport:
        """Execute complete Provenance Semiring defect evaluation.

        Args:
            evidence_list: Evidence from each analysis layer.
            witness_prob: Probability confirmation from L7 witness sandbox.
            source_code: Optional source code string to evaluate CC.
            ast_tree: Optional AST to evaluate CC.
            known_cc: Optional explicitly provided cyclomatic complexity.

        Returns:
            ProvenanceReport with complete metric provenance.
        """
        if known_cc is not None:
            cc = max(1, known_cc)
        elif ast_tree is not None:
            cc = compute_cyclomatic_complexity(ast_tree)
        elif source_code is not None:
            cc = compute_cyclomatic_complexity(source_code)
        else:
            cc = 1

        p_core = self.calculate_core_defect(evidence_list)
        p_fused, rho, confidence = self.fuse_evidence(p_core, witness_prob, cc)

        if confidence >= 0.60:
            verdict = "CONFIRMED_DEFECT"
        elif confidence >= 0.30:
            verdict = "SUSPECT"
        else:
            verdict = "CLEAN"

        layer_breakdown = {
            e.layer_name: {
                "status": e.status,
                "probability": e.probability,
                "weight": self.weights.get(e.layer_name, e.weight),
                "effective_d": e.effective_defect(),
            }
            for e in evidence_list
        }

        return ProvenanceReport(
            core_defect_probability=p_core,
            witness_probability=witness_prob,
            fused_probability=p_fused,
            cyclomatic_complexity=cc,
            damping_factor=rho,
            defect_confidence=confidence,
            verdict=verdict,
            layer_breakdown=layer_breakdown,
        )

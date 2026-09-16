"""
Tests for Repro Synthesizer Module.

Covers:
- WitnessGenerator
- DeterministicSandbox
- CrashValidator
- ReproSynthesizer
"""

import ast
import logging
import sys
import time
import unittest
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s - %(name)s - %(message)s'
)
sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

from src.core.repro_synthesizer import (
    WitnessGenerator,
    WitnessInput,
    WitnessOutput,
    DeterministicSandbox,
    DeterministicSandboxConfig,
    SandboxExecutionResult,
    CrashValidator,
    CrashReport,
    ReproSynthesizer,
    WitnessGenerationError,
    SandboxExecutionError,
    CrashValidationError,
    _ast_node_type,
    _get_node_name,
    _operator_str,
)


class TestASTNodeHelpers(unittest.TestCase):
    """Test AST node helper functions."""

    def test_ast_node_type_module(self):
        node = ast.Module(body=[], type_ignores=[])
        self.assertEqual(_ast_node_type(node), "Module")

    def test_ast_node_type_function_def(self):
        node = ast.FunctionDef(
            name="test",
            args=ast.arguments(args=[], vararg=None, kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=[]),
            body=[],
            decorator_list=[],
            returns=None,
            type_params=None,
        )
        self.assertEqual(_ast_node_type(node), "FunctionDef")

    def test_ast_node_type_class_def(self):
        node = ast.ClassDef(
            name="TestClass",
            bases=[],
            keywords=[],
            body=[],
        )
        self.assertEqual(_ast_node_type(node), "ClassDef")

    def test_ast_node_type_if(self):
        node = ast.If(test=ast.Constant(value=True), body=[], orelse=[])
        self.assertEqual(_ast_node_type(node), "If")

    def test_ast_node_type_for(self):
        node = ast.For(
            target=ast.Name(id="i", ctx=ast.Store()),
            iter=ast.Name(id="range", ctx=ast.Load()),
            body=[],
            orelse=[],
            type_comment=None,
        )
        self.assertEqual(_ast_node_type(node), "For")

    def test_ast_node_type_while(self):
        node = ast.While(test=ast.Constant(value=True), body=[], orelse=[])
        self.assertEqual(_ast_node_type(node), "While")

    def test_ast_node_type_return(self):
        node = ast.Return(value=None)
        self.assertEqual(_ast_node_type(node), "Return")

    def test_ast_node_type_name(self):
        node = ast.Name(id="x", ctx=ast.Load())
        self.assertEqual(_ast_node_type(node), "Name")

    def test_ast_node_type_constant(self):
        node = ast.Constant(value=42)
        self.assertEqual(_ast_node_type(node), "Constant")

    def test_ast_node_type_binop(self):
        left = ast.Name(id="x", ctx=ast.Load())
        right = ast.Name(id="y", ctx=ast.Load())
        op = ast.Add()
        node = ast.BinOp(left=left, op=op, right=right)
        self.assertEqual(_ast_node_type(node), "BinOp")

    def test_ast_node_type_call(self):
        func = ast.Name(id="print", ctx=ast.Load())
        node = ast.Call(func=func, args=[], keywords=[])
        self.assertEqual(_ast_node_type(node), "Call")

    def test_ast_node_type_list(self):
        elts = [ast.Constant(value=1), ast.Constant(value=2)]
        node = ast.List(elts=elts, ctx=ast.Load())
        self.assertEqual(_ast_node_type(node), "List")

    def test_ast_node_type_tuple(self):
        elts = [ast.Constant(value=1), ast.Constant(value=2)]
        node = ast.Tuple(elts=elts, ctx=ast.Load())
        self.assertEqual(_ast_node_type(node), "Tuple")

    def test_ast_node_type_dict(self):
        keys = [ast.Constant(value="a"), ast.Constant(value="b")]
        values = [ast.Constant(value=1), ast.Constant(value=2)]
        node = ast.Dict(keys=keys, values=values)
        self.assertEqual(_ast_node_type(node), "Dict")

    def test_ast_node_type_unknown(self):
        node = ast.expr_context()
        self.assertEqual(_ast_node_type(node), "expr_context")


class TestGetNodeName(unittest.TestCase):
    """Test _get_node_name helper."""

    def test_name_node(self):
        node = ast.Name(id="x", ctx=ast.Load())
        self.assertEqual(_get_node_name(node), "x")

    def test_attribute_node(self):
        node = ast.Attribute(value=ast.Name(id="obj", ctx=ast.Load()), attr="method", ctx=ast.Load())
        self.assertEqual(_get_node_name(node), "method")

    def test_constant_node(self):
        node = ast.Constant(value=42)
        self.assertEqual(_get_node_name(node), "42")

    def test_binop_node(self):
        left = ast.Name(id="x", ctx=ast.Load())
        right = ast.Name(id="y", ctx=ast.Load())
        op = ast.Add()
        node = ast.BinOp(left=left, op=op, right=right)
        self.assertEqual(_get_node_name(node), "x op y")


class TestOperatorStr(unittest.TestCase):
    """Test _operator_str helper."""

    def test_eq(self):
        self.assertEqual(_operator_str(ast.Eq()), "==")

    def test_ne(self):
        self.assertEqual(_operator_str(ast.NotEq()), "!=")

    def test_lt(self):
        self.assertEqual(_operator_str(ast.Lt()), "<")

    def test_gt(self):
        self.assertEqual(_operator_str(ast.Gt()), ">")

    def test_le(self):
        self.assertEqual(_operator_str(ast.LtE()), "<=")

    def test_ge(self):
        self.assertEqual(_operator_str(ast.GtE()), ">=")

    def test_is(self):
        self.assertEqual(_operator_str(ast.Is()), "is")

    def test_is_not(self):
        self.assertEqual(_operator_str(ast.IsNot()), "is not")

    def test_in(self):
        self.assertEqual(_operator_str(ast.In()), "in")

    def test_not_in(self):
        self.assertEqual(_operator_str(ast.NotIn()), "not in")


class TestWitnessGenerator(unittest.TestCase):
    """Test WitnessGenerator class."""

    def test_init_default(self):
        gen = WitnessGenerator(seed=42)
        self.assertEqual(gen.seed, 42)
        self.assertEqual(gen.file_path, "")
        self.assertEqual(gen.focus_line, None)

    def test_init_with_params(self):
        gen = WitnessGenerator(
            seed=123,
            file_path="/test/file.py",
            focus_line=10,
            octagon_constraints={"x": {"lower": 0, "upper": 100}},
            pep695_types={"T": "int"},
        )
        self.assertEqual(gen.seed, 123)
        self.assertEqual(gen.file_path, "/test/file.py")
        self.assertEqual(gen.focus_line, 10)

    def test_generate_empty_source(self):
        gen = WitnessGenerator(seed=42, file_path="/nonexistent/file.py")
        result = gen.generate(max_witnesses=10)
        self.assertEqual(len(result), 0)

    def test_generate_from_function(self):
        source = """
def add(a: int, b: int) -> int:
    return a + b
"""
        gen = WitnessGenerator(seed=42, file_path="/test.py")
        # Manually parse and generate
        tree = ast.parse(source)
        functions = gen._collect_functions(tree)
        self.assertGreaterEqual(len(functions), 1)

    def test_generate_boundary_witness(self):
        source = """
def process(x: int) -> int:
    if x > 0:
        return x * 2
    return 0
"""
        gen = WitnessGenerator(seed=42, file_path="/test.py")
        tree = ast.parse(source)
        functions = gen._collect_functions(tree)
        self.assertGreaterEqual(len(functions), 1)

    def test_generate_from_octagon_constraints(self):
        constraints = {"x": {"lower": 0, "upper": 100}, "y": {"lower": -10, "upper": 10}}
        gen = WitnessGenerator(seed=42, octagon_constraints=constraints)
        witness = gen._generate_constraint_witness()
        self.assertIsNotNone(witness)
        self.assertIn("x", witness.inputs)
        self.assertIn("y", witness.inputs)

    def test_generate_from_pep695_types(self):
        types = {"T": "int", "U": "str"}
        gen = WitnessGenerator(seed=42, pep695_types=types)
        witness = gen._generate_type_witness()
        self.assertIsNotNone(witness)
        self.assertIn("T", witness.inputs)
        self.assertIn("U", witness.inputs)

    def test_deduplicate(self):
        gen = WitnessGenerator(seed=42)
        # Create two witnesses with same inputs
        w1 = WitnessOutput(
            witness_id="W1",
            inputs={"x": 1},
            deterministic_hash="hash1",
        )
        w2 = WitnessOutput(
            witness_id="W2",
            inputs={"x": 1},
            deterministic_hash="hash2",
        )
        deduped = gen._deduplicate([w1, w2])
        self.assertEqual(len(deduped), 1)

    def test_next_witness_id(self):
        gen = WitnessGenerator(seed=42)
        id1 = gen._next_witness_id()
        id2 = gen._next_witness_id()
        self.assertNotEqual(id1, id2)


class TestDeterministicSandbox(unittest.TestCase):
    """Test DeterministicSandbox class."""

    def test_init_default(self):
        sandbox = DeterministicSandbox()
        self.assertEqual(sandbox.config.max_steps, 10000)
        self.assertEqual(sandbox.config.timeout_ms, 5000)

    def test_init_with_config(self):
        config = DeterministicSandboxConfig(
            max_steps=100,
            timeout_ms=1000,
            seed=99,
        )
        sandbox = DeterministicSandbox(config=config)
        self.assertEqual(sandbox.config.max_steps, 100)
        self.assertEqual(sandbox.config.timeout_ms, 1000)

    def test_execute_simple_code(self):
        sandbox = DeterministicSandbox()
        code = "result = 1 + 2"
        inputs = {}
        result = sandbox.execute(code, inputs)
        self.assertTrue(result.success)
        self.assertEqual(result.output, 3)

    def test_execute_with_inputs(self):
        sandbox = DeterministicSandbox()
        code = "result = x + y"
        inputs = {"x": 10, "y": 20}
        result = sandbox.execute(code, inputs)
        self.assertTrue(result.success)
        self.assertEqual(result.output, 30)

    def test_execution_state(self):
        sandbox = DeterministicSandbox()
        code = "result = 42"
        inputs = {}
        sandbox.execute(code, inputs)
        state = sandbox.get_execution_state()
        self.assertIn("step_counter", state)
        self.assertIn("execution_result", state)


class TestCrashValidator(unittest.TestCase):
    """Test CrashValidator class."""

    def test_init(self):
        validator = CrashValidator()
        self.assertEqual(len(validator._validated_crashes), 0)

    def test_validate_segfault(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="Segmentation fault",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    raise Segfault()\n",
            execution_steps=100,
        )
        self.assertEqual(report.crash_type, "segfault")
        self.assertEqual(report.execution_steps, 100)

    def test_validate_assertion(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="AssertionError",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    assert False\n",
            execution_steps=50,
        )
        self.assertEqual(report.crash_type, "assertion")

    def test_validate_timeout(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="Timeout",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    pass\nTimeout: exceeded\n",
            execution_steps=200,
        )
        self.assertEqual(report.crash_type, "timeout")

    def test_validate_memory_error(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="MemoryError",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    pass\n",
            execution_steps=300,
        )
        self.assertEqual(report.crash_type, "memory_exhausted")

    def test_validate_index_error(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="IndexError",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    pass\nlist index out of range\n",
            execution_steps=400,
        )
        self.assertEqual(report.crash_type, "index_error")

    def test_validate_type_error(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="TypeError",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    pass\nunsupported operand type\n",
            execution_steps=500,
        )
        self.assertEqual(report.crash_type, "type_error")

    def test_validate_value_error(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="ValueError",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    pass\ninvalid literal\n",
            execution_steps=600,
        )
        self.assertEqual(report.crash_type, "value_error")

    def test_validate_unknown(self):
        validator = CrashValidator()
        report = validator.validate(
            crash_type="SomeUnknownError",
            stack_trace="Traceback (most recent call last):\n  File \"test.py\", line 1\n    pass\n",
            execution_steps=700,
        )
        self.assertEqual(report.crash_type, "unknown")

    def test_get_crash_summary(self):
        validator = CrashValidator()
        validator.validate("segfault", stack_trace="segfault trace")
        validator.validate("segfault", stack_trace="segfault trace")
        validator.validate("assertion", stack_trace="assertion trace")
        summary = validator.get_crash_summary()
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["by_type"]["segfault"], 2)
        self.assertEqual(summary["by_type"]["assertion"], 1)

    def test_get_crash_reports(self):
        validator = CrashValidator()
        validator.validate("segfault", stack_trace="trace")
        reports = validator.get_crash_reports()
        self.assertEqual(len(reports), 1)


class TestReproSynthesizer(unittest.TestCase):
    """Test ReproSynthesizer class."""

    def test_init_default(self):
        synth = ReproSynthesizer(seed=42)
        self.assertEqual(synth.seed, 42)
        self.assertEqual(synth.max_witnesses, 100)

    def test_init_with_params(self):
        synth = ReproSynthesizer(
            file_path="/test.py",
            seed=123,
            max_witnesses=50,
        )
        self.assertEqual(synth.file_path, "/test.py")
        self.assertEqual(synth.seed, 123)
        self.assertEqual(synth.max_witnesses, 50)

    def test_generate_empty_file(self):
        synth = ReproSynthesizer(file_path="/nonexistent.py")
        result = synth.generate()
        self.assertEqual(len(result), 0)

    def test_generate_with_source(self):
        synth = ReproSynthesizer(
            file_path="/test.py",
            seed=42,
            max_witnesses=10,
        )
        # Write a test file
        import tempfile
        import os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("def add(a: int, b: int) -> int:\n    return a + b\n")
            temp_path = f.name

        try:
            result = synth.generate()
            self.assertIsInstance(result, list)
        finally:
            os.unlink(temp_path)

    def test_get_witness_report(self):
        synth = ReproSynthesizer(file_path="/test.py", seed=42)
        report = synth.get_witness_report()
        self.assertIn("file_path", report)
        self.assertIn("seed", report)
        self.assertIn("witnesses_generated", report)
        self.assertIn("crashes_detected", report)

    def test_get_witnesses(self):
        synth = ReproSynthesizer(file_path="/test.py", seed=42)
        witnesses = synth.get_witnesses()
        self.assertIsInstance(witnesses, list)

    def test_get_crash_reports(self):
        synth = ReproSynthesizer(file_path="/test.py", seed=42)
        reports = synth.get_crash_reports()
        self.assertIsInstance(reports, list)


if __name__ == "__main__":
    unittest.main()
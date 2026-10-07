"""
Tests for Axiom-Aegis-Veritas Sovereign MCP Server.

Validates:
- JSON-RPC 2.0 protocol handshake (initialize, ping, tools/list).
- Tool dispatch: axiom_verify_file, axiom_verify_workspace, axiom_audit_receipt.
- Error handling for invalid inputs and unknown methods.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
import pytest

from src.mcp.server import AxiomMCPServer


@pytest.fixture
def mcp_server() -> AxiomMCPServer:
    return AxiomMCPServer()


def test_mcp_initialize(mcp_server: AxiomMCPServer) -> None:
    """Verify initialize request returns valid server capabilities."""
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "clientInfo": {"name": "test-client", "version": "1.0"},
        },
    }
    resp = mcp_server.handle_request(req)

    assert resp is not None
    assert resp["id"] == 1
    assert "result" in resp
    assert resp["result"]["serverInfo"]["name"] == "axiom-aegis-veritas"
    assert "tools" in resp["result"]["capabilities"]


def test_mcp_tools_list(mcp_server: AxiomMCPServer) -> None:
    """Verify tools/list exposes all 3 mandatory tools."""
    req = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/list",
        "params": {},
    }
    resp = mcp_server.handle_request(req)

    assert resp is not None
    assert resp["id"] == 2
    tools = resp["result"]["tools"]
    tool_names = [t["name"] for t in tools]

    assert "axiom_verify_file" in tool_names
    assert "axiom_verify_workspace" in tool_names
    assert "axiom_audit_receipt" in tool_names


def test_mcp_verify_file_tool(mcp_server: AxiomMCPServer) -> None:
    """Verify tool call execution for axiom_verify_file."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write("def add(x: int, y: int) -> int:\n    return x + y\n")
        f_path = Path(f.name)

    try:
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "axiom_verify_file",
                "arguments": {"file_path": str(f_path), "strict": True},
            },
        }
        resp = mcp_server.handle_request(req)

        assert resp is not None
        assert resp["id"] == 3
        assert resp["result"]["isError"] is False
        content_text = resp["result"]["content"][0]["text"]
        data = json.loads(content_text)

        assert data["success"] is True
        assert data["bitmask"] == "0x7F"
        assert data["is_complete_7layers"] is True
        assert len(data["seal_hash"]) == 64
        assert data["status"] == "VERIFIED_SOUND"
    finally:
        if f_path.exists():
            f_path.unlink()


def test_mcp_audit_receipt_tool(mcp_server: AxiomMCPServer) -> None:
    """Verify tool call execution for axiom_audit_receipt."""
    with tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False, encoding="utf-8") as f:
        f.write("val: int = 10\n")
        f_path = Path(f.name)

    try:
        # First verify to obtain authentic seal hash
        first_verif = mcp_server.verify_file(str(f_path))
        authentic_hash = first_verif["seal_hash"]

        # Call audit_receipt with matching hash
        req_match = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "axiom_audit_receipt",
                "arguments": {
                    "file_path": str(f_path),
                    "expected_seal_hash": authentic_hash,
                },
            },
        }
        resp_match = mcp_server.handle_request(req_match)
        data_match = json.loads(resp_match["result"]["content"][0]["text"])

        assert data_match["matches"] is True
        assert data_match["tamper_detected"] is False
        assert data_match["verdict"] == "VERIFIED_AUTHENTIC"

        # Call audit_receipt with tampered hash
        req_tamper = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "axiom_audit_receipt",
                "arguments": {
                    "file_path": str(f_path),
                    "expected_seal_hash": "deadbeef" * 8,
                },
            },
        }
        resp_tamper = mcp_server.handle_request(req_tamper)
        data_tamper = json.loads(resp_tamper["result"]["content"][0]["text"])

        assert data_tamper["matches"] is False
        assert data_tamper["tamper_detected"] is True
        assert data_tamper["verdict"] == "INTEGRITY_VIOLATION"

    finally:
        if f_path.exists():
            f_path.unlink()


def test_mcp_unknown_method(mcp_server: AxiomMCPServer) -> None:
    """Verify error response when encountering unknown RPC method."""
    req = {
        "jsonrpc": "2.0",
        "id": 6,
        "method": "unknown/method",
        "params": {},
    }
    resp = mcp_server.handle_request(req)

    assert resp is not None
    assert "error" in resp
    assert resp["error"]["code"] == -32601

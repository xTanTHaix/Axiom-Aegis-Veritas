#!/usr/bin/env python3
"""
AXIOM-AEGIS-VERITAS Sovereign MCP Server Launcher.

Usage in MCP Configuration (e.g. ~/.gemini/config/mcp_config.json):
{
  "axiom": {
    "command": "python",
    "args": ["l:\\.Tool\\Axiom-Aegis-Veritas\\axiom_mcp.py"]
  }
}
"""

import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.mcp.server import main

if __name__ == "__main__":
    main()

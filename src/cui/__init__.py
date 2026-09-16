"""
AXIOM-AEGIS-VERITAS CLI Modules Package.

Exports:
- ProgressBar: ANSI progress bar with spinner
- TerminalDashboard: Terminal dashboard renderer
- FileWatcher: Real-time file watcher
- PrettyLogger: Structured telemetry logger
- ResultFormatter: Verification result formatter
"""

from src.cui.progress_bar import ProgressBar, ProgressConfig
from src.cui.console_view import TerminalDashboard, DashboardConfig, Card
from src.cui.cli_watcher import FileWatcher, FileEvent, WatchConfig, create_watcher
from src.cui.pretty_logger import PrettyLogger, LogConfig, LogFormatter
from src.cui.result_formatter import (
    ResultFormatter,
    Result,
    ReportGenerator,
    ResultConfig,
    TextFormatter,
    JSONFormatter,
    XMLFormatter,
    HTMLFormatter,
    MarkdownFormatter,
)

__all__ = [
    "ProgressBar",
    "ProgressConfig",
    "TerminalDashboard",
    "DashboardConfig",
    "Card",
    "FileWatcher",
    "FileEvent",
    "WatchConfig",
    "create_watcher",
    "PrettyLogger",
    "LogConfig",
    "LogFormatter",
    "ResultFormatter",
    "Result",
    "ReportGenerator",
    "ResultConfig",
    "TextFormatter",
    "JSONFormatter",
    "XMLFormatter",
    "HTMLFormatter",
    "MarkdownFormatter",
]

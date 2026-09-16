"""
CLI Module: Terminal Dashboard Renderer with Card-based Status Displays.

Features:
- Card-based status displays for multiple metrics
- Real-time dashboard updates
- Color-coded status indicators
- Support for multiple view modes
- Customizable layout and styling
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import sys
from colorama import Fore, Style, init

init(autoreset=True)


@dataclass
class DashboardConfig:
    """Configuration for terminal dashboard."""

    width: int = 80
    height: int = 24
    card_width: int = 50
    card_height: int = 12
    show_title: bool = True
    show_footer: bool = True
    theme: str = "default"
    background_color: str = "black"
    foreground_color: str = "white"


class Card:
    """Terminal card for displaying metrics."""

    def __init__(
        self,
        title: str,
        data: Dict[str, Any],
        config: Optional[DashboardConfig] = None,
    ) -> None:
        """Initialize card.

        Args:
            title: Card title.
            data: Dictionary of metric data.
            config: Optional dashboard configuration.
        """
        self.title = title
        self.data = data
        self.config = config or DashboardConfig()
        self._width = self.config.card_width
        self._height = self.config.card_height
        self._padding = 1

    def __repr__(self) -> str:
        """Return string representation of card."""
        return f"Card(title={self.title}, data={self.data})"

    def _format_metric(self, key: str, value: Any) -> str:
        """Format a single metric value."""
        if isinstance(value, (int, float)):
            if "." in str(value):
                return f"{value:.2f}"
            return f"{value}"
        return str(value)

    def _format_data_row(self, key: str, value: Any) -> str:
        """Format a data row with proper alignment."""
        label = f"{key}"
        formatted_value = self._format_metric(key, value)
        return f"{label:<{self._width - len(label) - 2}} {formatted_value}"

    def _render_body(self) -> str:
        """Render card body content."""
        rows = []
        for key in sorted(self.data.keys()):
            value = self.data[key]
            if key == "status":
                status_str = str(value).upper()
                if "success" in status_str.lower():
                    rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.GREEN}{value}{Style.RESET_ALL}")
                elif "error" in status_str.lower():
                    rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.RED}{value}{Style.RESET_ALL}")
                else:
                    rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.YELLOW}{value}{Style.RESET_ALL}")
            elif key == "progress":
                progress_str = str(value)
                bar_width = max(1, int(self._width - len(key) - 2))
                filled = int(bar_width * value / 100) if value <= 100 else bar_width
                rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.GREEN}{Fore.WHITE}{Fore.BLACK}{'|' * filled}{Style.RESET_ALL}")
            elif key == "value":
                formatted_value = self._format_metric(key, value)
                rows.append(f"{key:<{self._width - len(key) - 2}} {formatted_value}")
            elif key == "count":
                formatted_value = self._format_metric(key, value)
                rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.CYAN}{value}{Style.RESET_ALL}")
            else:
                formatted_value = self._format_metric(key, value)
                rows.append(self._format_data_row(key, value))

        return "\n".join(rows) if rows else ""
        rows = []
        for key in sorted(self.data.keys()):
            value = self.data[key]
            if key == "status":
                status_str = str(value).upper()
                if "success" in status_str.lower():
                    rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.GREEN}{value}{Style.RESET_ALL}")
                elif "error" in status_str.lower():
                    rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.RED}{value}{Style.RESET_ALL}")
                else:
                    rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.YELLOW}{value}{Style.RESET_ALL}")
            elif key == "progress":
                progress_str = str(value)
                bar_width = max(1, int(self._width - len(key) - 2))
                filled = int(bar_width * value / 100) if value <= 100 else bar_width
                rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.GREEN}{Fore.WHITE}{Fore.BLACK}{'|' * filled}{Style.RESET_ALL}")
            elif key == "value":
                formatted_value = self._format_metric(key, value)
                rows.append(f"{key:<{self._width - len(key) - 2}} {formatted_value}")
            elif key == "count":
                formatted_value = self._format_metric(key, value)
                rows.append(f"{key:<{self._width - len(key) - 2}} {Fore.CYAN}{value}{Style.RESET_ALL}")
            else:
                formatted_value = self._format_metric(key, value)
                rows.append(self._format_data_row(key, value))

        return "\n".join(rows) if rows else ""

    def render(self) -> str:
        """Render card as string."""
        title_line = f"{Fore.WHITE}{self.title}{Style.RESET_ALL}"
        body = self._render_body()

        if self._height > 1:
            separator = f"{Fore.WHITE}{Style.RESET_ALL}" * self._width
            return f"{title_line}\n{separator}\n{body}\n{separator}"
        return f"{title_line}\n{body}"


class TerminalDashboard:
    """Terminal dashboard renderer with multiple card support."""

    def __init__(
        self,
        config: Optional[DashboardConfig] = None,
    ) -> None:
        """Initialize dashboard.

        Args:
            config: Optional dashboard configuration.
        """
        self.config = config or DashboardConfig()
        self.cards: List[Card] = []
        self._running = True

    def add_card(self, card: Card) -> None:
        """Add card to dashboard.

        Args:
            card: Card to add.
        """
        self.cards.append(card)

    def remove_card(self, card: Card) -> None:
        """Remove card from dashboard.

        Args:
            card: Card to remove.
        """
        if card in self.cards:
            self.cards.remove(card)

    def update_card(self, card: Card, new_data: Dict[str, Any]) -> None:
        """Update card data in real-time.

        Args:
            card: Card to update.
            new_data: New data dictionary.
        """
        for c in self.cards:
            if c == card:
                c.data = new_data
                break

    def _render_card(self, card: Card) -> str:
        """Render a single card."""
        return card.render()

    def _render_separator(self) -> str:
        """Render horizontal separator line."""
        return f"{Fore.WHITE}{Style.RESET_ALL}" * (self.config.width - 2)

    def _render_title(self) -> str:
        """Render dashboard title."""
        if self.config.show_title:
            title = f"{Fore.CYAN}AXIOM-AEGIS-VERITAS{Style.RESET_ALL} - Terminal Dashboard"
            return title.center(self.config.width)
        return ""

    def _render_footer(self) -> str:
        """Render dashboard footer."""
        if self.config.show_footer:
            footer = f"{Fore.GREEN}Ready{Style.RESET_ALL} | {Fore.CYAN}Press Ctrl+C to exit{Style.RESET_ALL}"
            return footer.center(self.config.width)
        return ""

    def render_all(self) -> str:
        """Render entire dashboard."""
        lines = []

        # Title
        lines.append(self._render_title())
        lines.append(self._render_separator())

        # Cards
        for card in self.cards:
            lines.append(self._render_card(card))
            lines.append(self._render_separator())

        # Footer
        lines.append(self._render_footer())

        return "\n".join(lines)

    def refresh(self) -> str:
        """Refresh and render dashboard."""
        return self.render_all()

    def is_running(self) -> bool:
        """Check if dashboard is running."""
        return self._running

    def stop(self) -> None:
        """Stop dashboard."""
        self._running = False

    def __iter__(self) -> "TerminalDashboard":
        """Enable iteration for dashboard."""
        return self

    def __next__(self) -> str:
        """Get next dashboard frame."""
        if self._running:
            return self.render_all()
        raise StopIteration


def render_terminal_report(results: Dict[str, Any], elapsed_time: float = 0.0) -> str:
    """Render a comprehensive terminal dashboard report from analysis results.

    Args:
        results: Dictionary mapping layer names (or filenames) to layer results.
        elapsed_time: Total elapsed execution time in seconds.

    Returns:
        Rendered ANSI terminal dashboard string.
    """
    config = DashboardConfig(width=80, card_width=76, show_title=True, show_footer=True)
    dashboard = TerminalDashboard(config=config)

    # General execution card
    passed_count = sum(1 for v in results.values() if "ERROR" not in str(v) and "FAIL" not in str(v))
    total_count = len(results)
    health_status = "HEALTHY" if passed_count == total_count and total_count > 0 else "DEFECTS DETECTED"

    summary_data = {
        "Status": health_status,
        "Total Layers/Items": total_count,
        "Passed": passed_count,
        "Failed": total_count - passed_count,
        "Elapsed Time": f"{elapsed_time:.3f}s",
    }
    dashboard.add_card(Card(title="Executive Summary", data=summary_data, config=config))

    # Layer details cards
    for layer_name, layer_res in results.items():
        if isinstance(layer_res, dict):
            card_data = {str(k): str(v) for k, v in layer_res.items()}
        else:
            is_err = "ERROR" in str(layer_res) or "FAIL" in str(layer_res)
            card_data = {
                "Verdict": "FAIL" if is_err else "PASS",
                "Details": str(layer_res)[:60],
            }
        dashboard.add_card(Card(title=f"Layer: {layer_name}", data=card_data, config=config))

    return dashboard.render_all()


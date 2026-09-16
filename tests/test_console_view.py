"""
AXIOM-AEGIS-VERITAS — Test Suite for CUI: Console View / Terminal Dashboard.
20 tests covering Card, TerminalDashboard, DashboardConfig, and rendering.
"""

import re
from colorama import Fore, Style

import pytest

from src.cui.console_view import Card, DashboardConfig, TerminalDashboard


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture
def default_config():
    """Return a default DashboardConfig."""
    return DashboardConfig()


@pytest.fixture
def custom_config():
    """Return a custom DashboardConfig."""
    return DashboardConfig(
        width=100,
        height=30,
        card_width=60,
        card_height=15,
        show_title=True,
        show_footer=True,
        theme="dark",
    )


@pytest.fixture
def sample_card(default_config):
    """Return a sample Card with some data."""
    card = Card(
        title="Layer 1 Status",
        data={"status": "success", "progress": 75, "value": 42, "count": 10},
        config=default_config,
    )
    return card


@pytest.fixture
def sample_card_error(default_config):
    """Return a sample Card with error status."""
    return Card(
        title="Layer 3 Status",
        data={"status": "error", "value": "timeout"},
        config=default_config,
    )


@pytest.fixture
def sample_card_warning(default_config):
    """Return a sample Card with warning status."""
    return Card(
        title="Layer 5 Status",
        data={"status": "warning", "value": "partial"},
        config=default_config,
    )


@pytest.fixture
def dashboard(default_config):
    """Return a sample TerminalDashboard."""
    dash = TerminalDashboard(config=default_config)
    dash.add_card(Card(title="Layer 1 Status", data={"status": "success", "progress": 75, "value": 42, "count": 10}, config=default_config))
    dash.add_card(Card(title="Layer 3 Status", data={"status": "error", "value": "timeout"}, config=default_config))
    return dash


# ─── Tests: DashboardConfig ─────────────────────────────────────────────────

class TestDashboardConfig:
    """Tests for DashboardConfig class."""

    def test_default_values(self):
        """Test default configuration values."""
        config = DashboardConfig()
        assert config.width == 80
        assert config.height == 24
        assert config.card_width == 50
        assert config.card_height == 12
        assert config.show_title is True
        assert config.show_footer is True
        assert config.theme == "default"

    def test_custom_values(self):
        """Test custom configuration values."""
        config = DashboardConfig(width=120, height=40, card_width=70, card_height=20)
        assert config.width == 120
        assert config.height == 40
        assert config.card_width == 70
        assert config.card_height == 20

    def test_show_title_false(self):
        """Test show_title=False."""
        config = DashboardConfig(show_title=False)
        assert config.show_title is False

    def test_show_footer_false(self):
        """Test show_footer=False."""
        config = DashboardConfig(show_footer=False)
        assert config.show_footer is False

    def test_custom_theme(self):
        """Test custom theme."""
        config = DashboardConfig(theme="dark")
        assert config.theme == "dark"


# ─── Tests: Card ────────────────────────────────────────────────────────────

class TestCard:
    """Tests for Card class."""

    def test_card_creation(self):
        """Test card creation."""
        card = Card(title="Test", data={"key": "value"})
        assert card.title == "Test"
        assert card.data == {"key": "value"}

    def test_card_default_config(self):
        """Test card with default config."""
        card = Card(title="Test", data={"key": "value"})
        assert card.config is not None
        assert card.config.width == 80

    def test_card_custom_config(self):
        """Test card with custom config."""
        config = DashboardConfig(card_width=60, card_height=10)
        card = Card(title="Test", data={"key": "value"}, config=config)
        assert card.config.card_width == 60
        assert card.config.card_height == 10

    def test_card_render_basic(self, sample_card):
        """Test basic card rendering."""
        rendered = sample_card.render()
        assert "Layer 1 Status" in rendered
        assert "success" in rendered.lower()

    def test_card_render_with_error(self, sample_card_error):
        """Test card rendering with error status."""
        rendered = sample_card_error.render()
        assert "Layer 3 Status" in rendered
        assert "error" in rendered.lower()

    def test_card_render_with_warning(self, sample_card_warning):
        """Test card rendering with warning status."""
        rendered = sample_card_warning.render()
        assert "Layer 5 Status" in rendered
        assert "warning" in rendered.lower()

    def test_card_render_with_progress(self, default_config):
        """Test card rendering with progress metric."""
        card = Card(
            title="Progress",
            data={"progress": 85},
            config=default_config,
        )
        rendered = card.render()
        assert "Progress" in rendered

    def test_card_render_empty_data(self):
        """Test card rendering with empty data."""
        card = Card(title="Empty", data={})
        rendered = card.render()
        assert "Empty" in rendered

    def test_card_render_integer_value(self, default_config):
        """Test card rendering with integer value."""
        card = Card(
            title="Value",
            data={"value": 42},
            config=default_config,
        )
        rendered = card.render()
        assert "42" in rendered

    def test_card_render_float_value(self, default_config):
        """Test card rendering with float value."""
        card = Card(
            title="Value",
            data={"value": 3.14},
            config=default_config,
        )
        rendered = card.render()
        assert "3.14" in rendered

    def test_card_render_count(self, default_config):
        """Test card rendering with count metric."""
        card = Card(
            title="Count",
            data={"count": 100},
            config=default_config,
        )
        rendered = card.render()
        assert "Count" in rendered

    def test_card_repr(self):
        """Test card representation."""
        card = Card(title="Test", data={"key": "value"})
        repr_str = repr(card)
        assert "Card" in repr_str
        assert "Test" in repr_str

    def test_card_str(self):
        """Test card string conversion."""
        card = Card(title="Test", data={"key": "value"})
        str(card)
        # Should not raise

    def test_card_title_case(self):
        """Test card title is preserved."""
        card = Card(title="My Title", data={})
        assert card.title == "My Title"


# ─── Tests: TerminalDashboard ───────────────────────────────────────────────

class TestTerminalDashboard:
    """Tests for TerminalDashboard class."""

    def test_dashboard_creation(self, default_config):
        """Test dashboard creation."""
        dash = TerminalDashboard(config=default_config)
        assert dash is not None
        assert dash.config.width == 80

    def test_dashboard_add_card(self, default_config):
        """Test adding a card to dashboard."""
        dash = TerminalDashboard(config=default_config)
        card = Card(title="Card 1", data={"status": "ok"})
        dash.add_card(card)
        assert len(dash.cards) == 1

    def test_dashboard_remove_card(self, dashboard):
        """Test removing a card from dashboard."""
        dash = dashboard
        first_card = dash.cards[0]
        dash.remove_card(first_card)
        assert len(dash.cards) == 1

    def test_dashboard_remove_nonexistent_card(self, dashboard):
        """Test removing a card that does not exist."""
        dash = dashboard
        fake_card = Card(title="Fake", data={})
        dash.remove_card(fake_card)
        assert len(dash.cards) == 2

    def test_dashboard_update_card(self, default_config):
        """Test updating card data."""
        dash = TerminalDashboard(config=default_config)
        card = Card(title="Card 1", data={"status": "old"})
        dash.add_card(card)
        dash.update_card(card, {"status": "new"})
        assert card.data["status"] == "new"

    def test_dashboard_render_all(self, dashboard):
        """Test rendering all cards."""
        rendered = dashboard.render_all()
        assert "AXIOM-AEGIS-VERITAS" in rendered
        assert "Layer 1 Status" in rendered
        assert "Layer 3 Status" in rendered

    def test_dashboard_render_no_cards(self, default_config):
        """Test rendering with no cards."""
        dash = TerminalDashboard(config=default_config)
        rendered = dash.render_all()
        assert "AXIOM-AEGIS-VERITAS" in rendered
        assert "Layer" not in rendered

    def test_dashboard_is_running(self):
        """Test dashboard running state."""
        dash = TerminalDashboard()
        assert dash.is_running() is True

    def test_dashboard_stop(self):
        """Test stopping dashboard."""
        dash = TerminalDashboard()
        dash.stop()
        assert dash.is_running() is False

    def test_dashboard_refresh(self, dashboard):
        """Test dashboard refresh."""
        rendered = dashboard.refresh()
        assert "AXIOM-AEGIS-VERITAS" in rendered

    def test_dashboard_iteration(self, dashboard):
        """Test dashboard iteration."""
        dash = dashboard
        assert hasattr(dash, "__iter__")
        assert hasattr(dash, "__next__")

    def test_dashboard_repr(self):
        """Test dashboard representation."""
        dash = TerminalDashboard()
        repr_str = repr(dash)
        assert "TerminalDashboard" in repr_str

    def test_dashboard_str(self):
        """Test dashboard string conversion."""
        dash = TerminalDashboard()
        str(dash)
        # Should not raise

    def test_dashboard_multiple_cards(self, default_config):
        """Test dashboard with multiple cards."""
        dash = TerminalDashboard(config=default_config)
        for i in range(5):
            card = Card(title=f"Card {i}", data={"status": "ok"})
            dash.add_card(card)
        assert len(dash.cards) == 5

    def test_dashboard_footer_config(self, default_config):
        """Test dashboard with footer disabled."""
        no_footer = DashboardConfig(show_footer=False)
        dash = TerminalDashboard(config=no_footer)
        rendered = dash.render_all()
        assert "Ready" not in rendered

    def test_dashboard_title_config(self, default_config):
        """Test dashboard with title disabled."""
        no_title = DashboardConfig(show_title=False)
        dash = TerminalDashboard(config=no_title)
        rendered = dash.render_all()
        assert "AXIOM-AEGIS-VERITAS" not in rendered
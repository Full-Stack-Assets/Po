"""Unit tests for runtime configuration module."""

import json
from unittest.mock import MagicMock, patch

import pytest

from orchestrator_agent.config_api import (
    ConfigManager,
    SystemConfig,
    config_to_dict,
)


def _make_constraint(name, current_value=0.0, max_value=100.0, unit="tokens"):
    c = MagicMock()
    c.name = name
    c.current_value = current_value
    c.max_value = max_value
    c.unit = unit
    return c


def _make_orchestrator():
    orch = MagicMock()

    # ── llm (LLMManager) ──
    llm = MagicMock()
    llm._configs = {}
    llm._providers = {}
    llm._health = {}
    orch.llm = llm

    # ── constraint_engine ──
    token_c = _make_constraint("token_budget", 50.0, 1000.0, "tokens")
    cost_c = _make_constraint("cost_budget", 0.5, 10.0, "usd")
    ce = MagicMock()
    ce._constraints = {"token_budget": token_c, "cost_budget": cost_c}
    ce.reset_all = MagicMock()
    orch.constraint_engine = ce

    # ── config dict ──
    orch.config = {"environment": "testing", "trust_layer": {}}

    # ── approval_manager ──
    orch.approval_manager = MagicMock()
    orch.approval_manager.auto_approve = True

    # ── verification_layer ──
    orch.verification_layer = MagicMock()
    orch.verification_layer.fail_on_unverified = False

    return orch


# ── get_config ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_config():
    orch = _make_orchestrator()
    mgr = ConfigManager(orch)

    with patch("orchestrator_agent.tools.default_tool_registry") as mock_reg:
        mock_reg.return_value.list_tools.return_value = []
        config = await mgr.get_config()

    assert isinstance(config, SystemConfig)
    assert isinstance(config.constraints, list)
    assert len(config.constraints) == 2
    assert config.trust.auto_approve is True
    assert config.environment == "testing"


# ── config_to_dict ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_config_to_dict():
    orch = _make_orchestrator()
    mgr = ConfigManager(orch)

    with patch("orchestrator_agent.tools.default_tool_registry") as mock_reg:
        mock_reg.return_value.list_tools.return_value = []
        config = await mgr.get_config()

    d = config_to_dict(config)
    # Must be JSON-serializable
    serialized = json.dumps(d)
    assert '"environment": "testing"' in serialized
    assert "constraints" in d
    assert "trust" in d
    assert "providers" in d


# ── update_constraints ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_constraints():
    orch = _make_orchestrator()
    mgr = ConfigManager(orch)
    result = await mgr.update_constraints(max_cost=25.0)

    # The cost_budget constraint should have been updated
    cost_c = orch.constraint_engine._constraints["cost_budget"]
    assert cost_c.max_value == 25.0

    # Result is a list of ConstraintSetting
    assert len(result) == 2


# ── reset_budgets ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_budgets():
    orch = _make_orchestrator()
    mgr = ConfigManager(orch)
    result = await mgr.reset_budgets()

    orch.constraint_engine.reset_all.assert_called_once()
    assert len(result) == 2
    for cs in result:
        assert hasattr(cs, "name")
        assert hasattr(cs, "current_used")
        assert hasattr(cs, "max_value")

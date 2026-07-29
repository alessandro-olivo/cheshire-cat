"""Mistakes a plugin author makes should say so, not go quiet.

Discovery *warns* (a plugin still loads); misuse *raises* with a typed error
whose message names the fix.
"""

import pytest

from cat.errors import CatError, PluginError, ServiceNotFound


@pytest.fixture
def warnings_logged():
    """Collect WARNING lines. The Cat logs through loguru, which `caplog` (a
    stdlib logging fixture) never sees — so we attach a sink instead."""
    from loguru import logger

    messages = []
    sink_id = logger.add(lambda m: messages.append(str(m)), level="WARNING")
    yield messages
    logger.remove(sink_id)


@pytest.fixture
async def cheshire_cat(booted_app):
    """The live cat, bootstrapped in this test's own event loop."""
    from cat.ambient.runtime import ccat

    return ccat()


async def test_missing_service_names_what_is_registered(cheshire_cat):
    with pytest.raises(ServiceNotFound) as excinfo:
        await cheshire_cat.get("model_providers", "nonexistent")

    error = excinfo.value
    assert error.slug == "nonexistent"
    assert "default" in error.available          # what IS there
    assert "default" in str(error)


async def test_missing_service_suggests_a_close_name(cheshire_cat):
    """A near-miss slug gets a 'did you mean'."""
    with pytest.raises(ServiceNotFound, match="Did you mean 'default'"):
        await cheshire_cat.get("model_providers", "defualt")


async def test_service_not_found_is_a_cat_error(cheshire_cat):
    """Typed, so an agent (or a plugin) can branch on it."""
    with pytest.raises(CatError):
        await cheshire_cat.get("agents", "nope")


async def test_unregistered_service_settings_fail_loudly():
    """Used to silently compute `settings_None_...`, shared by every stray service."""
    from pydantic import BaseModel
    from cat.services.service import Service

    class Stray(Service):
        service_type = "strays"
        slug = "stray"

        class Settings(BaseModel):
            colour: str = "grey"

    assert Stray.plugin_id is None

    with pytest.raises(PluginError, match="not registered"):
        await Stray.load_settings()


def test_typo_in_a_hook_name_is_warned_about():
    """`before_agent_ran` is one letter from a real hook — say so."""
    from cat.mad_hatter.decorators.hook import CORE_HOOKS
    from cat.errors import _did_you_mean

    assert _did_you_mean("before_agent_ran", list(CORE_HOOKS)) == "before_agent_run"


def test_a_plugins_own_hook_name_is_not_warned_about():
    """Plugins may fire hooks by any name; only near-misses are suspicious."""
    from cat.mad_hatter.decorators.hook import CORE_HOOKS
    from cat.errors import _did_you_mean

    assert _did_you_mean("after_file_upload", list(CORE_HOOKS)) is None


async def test_unknown_directive_slug_warns_at_discovery(cheshire_cat, warnings_logged):
    """A bad slug used to surface only when the agent first ran."""
    from cat.base import Agent

    class BadDirectiveAgent(Agent):
        slug = "baddirective"
        directives = ["definitely_not_registered"]

    cheshire_cat.mad_hatter.service_classes.setdefault("agents", {})[
        "baddirective"
    ] = BadDirectiveAgent

    cheshire_cat.mad_hatter._warn_about_likely_mistakes()

    assert any("definitely_not_registered" in m for m in warnings_logged), warnings_logged


async def test_module_level_tool_warns(cheshire_cat, warnings_logged):
    """A `@tool` outside an Agent is unreachable — discovery says so."""
    from cat import tool

    @tool
    def orphan_tool(self):
        """A tool nothing can reach."""
        return "nothing"

    # stand in for a plugin that declared it at module level (the core suite
    # boots with zero plugins, so we supply the shape discovery would see)
    class FakePlugin:
        id = "demo"
        module_level_tools = [("orphan_tool", orphan_tool)]

    cheshire_cat.mad_hatter.plugins["demo"] = FakePlugin()

    cheshire_cat.mad_hatter._warn_about_likely_mistakes()

    assert any("orphan_tool" in m for m in warnings_logged), warnings_logged

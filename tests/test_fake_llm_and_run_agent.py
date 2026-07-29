"""The in-process authoring loop: script an LLM, run an agent, inspect both.

These are the harness's own tests, and they double as the reference for what a
plugin test looks like — no server, no HTTP, no SSE.
"""

import pytest

from cat import tool
from cat.base import Agent
from cat.testing.fake_llm import EXHAUSTED_REPLY


class GreeterAgent(Agent):
    """An agent with one tool, defined right here in the test."""

    slug = "greeter"
    system_prompt = "You greet people."

    @tool
    def greet(self, name: str):
        """Greet someone by name."""
        return f"hello {name}"


@pytest.fixture
def greeter(booted_app):
    """Register the test-local agent for the duration of a test."""
    from cat.ambient.runtime import ccat

    ccat().registry.register(GreeterAgent)
    return GreeterAgent


async def test_run_agent_returns_the_scripted_answer(fake_llm, run_agent):
    fake_llm.reply_text("hello there")

    result = await run_agent("default", "hi")

    assert result.messages[-1].text == "hello there"


async def test_recorded_call_exposes_what_the_llm_saw(fake_llm, run_agent):
    fake_llm.reply_text("noted")

    await run_agent("default", "remind me to buy milk")

    assert len(fake_llm.calls) == 1
    call = fake_llm.calls[0]
    assert call.messages[-1].text == "remind me to buy milk"
    assert call.system_prompt  # the default agent's prompt reached the provider


async def test_scripted_tool_call_then_answer(fake_llm, run_agent, greeter):
    """Turn 1 calls the tool, turn 2 answers — the loop runs for real."""
    fake_llm.reply_with_tool("greet", name="Alice")
    fake_llm.reply_text("done")

    result = await run_agent("greeter", "say hi to Alice")

    # assistant tool call → tool result → final answer
    tool_messages = [m for m in result.messages if m.role == "tool"]
    assert len(tool_messages) == 1
    assert tool_messages[0].text == "hello Alice"
    assert result.messages[-1].text == "done"

    # two turns, and the second one saw the tool result
    assert len(fake_llm.calls) == 2
    assert fake_llm.calls[1].messages[-1].text == "hello Alice"


async def test_agent_tools_are_offered_to_the_provider(fake_llm, run_agent, greeter):
    fake_llm.reply_text("nothing to do")

    await run_agent("greeter", "hi")

    assert "greet" in fake_llm.calls[0].tool_names


async def test_exhausted_queue_terminates_the_loop(fake_llm, run_agent):
    """An under-scripted test must fail on an assertion, never hang."""
    result = await run_agent("default", "hi")

    assert result.messages[-1].text == EXHAUSTED_REPLY


async def test_ambient_user_resolves_inside_a_tool(fake_llm, run_agent, booted_app):
    """`from cat import user` works inside a run, as it does under a request."""
    from cat.ambient.runtime import ccat
    from cat import user

    seen = {}

    class WhoAmIAgent(Agent):
        slug = "whoami"

        @tool
        def whoami(self):
            """Report the current user."""
            seen["name"] = user.name
            return user.name

    ccat().registry.register(WhoAmIAgent)

    fake_llm.reply_with_tool("whoami")
    fake_llm.reply_text("ok")

    await run_agent("whoami", "who am I?")

    assert seen["name"] == "test"


async def test_provider_resolves_through_the_registry(fake_llm):
    """No special casing: `llm()` finds it the way it finds any provider."""
    from cat.ambient import llm
    from cat.ambient.context_vars import Ctx, use_ctx

    fake_llm.reply_text("via the registry")

    with use_ctx(Ctx(user=None)):
        message = await llm("say something", stream=False)

    assert message.text == "via the registry"
    assert fake_llm.calls[0].system_prompt == ""  # promoted to a user message

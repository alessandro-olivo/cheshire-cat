"""
A programmable LLM for tests — and a window onto what the model actually saw.

`fake_llm` is a real `ModelProvider`, resolved through the normal registry path.
Nothing in agent code is patched, so a test exercises the same machinery
production does; the only difference is that the replies are scripted by you
instead of sampled by a model.

Two things it does:

**Script the replies.** Queue them in the order the loop will consume them:

    fake_llm.reply_with_tool("create_todo", text="milk")   # turn 1: call a tool
    fake_llm.reply_text("added it")                        # turn 2: final answer

**Inspect the input.** Every invocation is recorded, so you can assert on the
exact conversation the provider received:

    assert fake_llm.calls[0].messages[-1].text == "remind me to buy milk"
    assert "create_todo" in [t.name for t in fake_llm.calls[0].tools]

When the queue runs dry the provider answers with a plain text message and no
tool calls, so an agentic loop always terminates instead of hanging a test.
"""

from dataclasses import dataclass, field
from typing import List, TYPE_CHECKING
from uuid import uuid4

from cat.services.model_providers.base import ModelProvider
from cat.types import Message, TextContent, ToolCall

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from cat.mad_hatter.decorators import Tool


# Answer given once the scripted queue is exhausted. Deliberately tool-free: an
# agentic loop ends when a reply carries no tool calls, so an under-scripted test
# fails on an assertion rather than spinning forever.
EXHAUSTED_REPLY = "fake_llm has no more scripted replies."


@dataclass
class RecordedCall:
    """One invocation of the provider, exactly as the agent made it."""

    model: str
    messages: List[Message]
    system_prompt: str
    tools: List["Tool"]

    @property
    def tool_names(self) -> List[str]:
        return [t.name for t in self.tools]


@dataclass
class _Scripted:
    """A queued reply: some text, and optionally tool calls to request."""

    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)


class FakeModelProvider(ModelProvider):
    """A `ModelProvider` whose replies are scripted and whose calls are recorded.

    Registered by the `fake_llm` fixture, never by discovery — it is not a
    plugin and never reaches a running Cat.
    """

    slug = "fake"
    name = "Fake LLM (testing)"
    description = "Programmable model provider for tests."

    # `ModelProvider` is a singleton, so the fixture's handle and whatever
    # `llm()` resolves are the same object. The fixture resets this state
    # between tests.
    def __init__(self):
        self.scripted: List[_Scripted] = []
        self.calls: List[RecordedCall] = []

    # -- scripting ---------------------------------------------------------

    def reply_text(self, text: str) -> "FakeModelProvider":
        """Queue a plain assistant answer (ends the agentic loop)."""
        self.scripted.append(_Scripted(text=text))
        return self

    def reply_with_tool(
        self, tool_name: str, /, _text: str = "", **args
    ) -> "FakeModelProvider":
        """Queue an assistant turn that calls `tool_name` with `**args` as arguments.

        Keyword arguments become the tool's arguments, so the call reads like the
        tool signature: `reply_with_tool("create_todo", text="milk")`. Pass
        `_text=` for assistant text alongside the tool call (rare).

        `tool_name` is positional-only and the text parameter is underscored on
        purpose: a tool is free to have arguments called `name` or `text`, and
        those must land in `**args` rather than collide with this signature.
        """
        self.scripted.append(
            _Scripted(
                text=_text,
                tool_calls=[ToolCall(id=str(uuid4()), name=tool_name, args=args)],
            )
        )
        return self

    def reset(self) -> None:
        """Drop scripted replies and recorded calls."""
        self.scripted.clear()
        self.calls.clear()

    # -- provider interface ------------------------------------------------

    async def list_llms(self) -> List[str]:
        return ["fake"]

    async def list_embedders(self) -> List[str]:
        return ["fake"]

    async def llm(
        self,
        model: str,
        messages: list[Message],
        system_prompt: str = "",
        tools: list["Tool"] = [],
        on_token: "Callable[[str], Awaitable[None]] | None" = None,
        on_tool_call: "Callable[[ToolCall], Awaitable[None]] | None" = None,
    ) -> Message:
        self.calls.append(
            RecordedCall(
                model=model,
                messages=list(messages),
                system_prompt=system_prompt,
                tools=list(tools),
            )
        )

        reply = (
            self.scripted.pop(0) if self.scripted else _Scripted(text=EXHAUSTED_REPLY)
        )

        # Stream word by word when the caller asked for streaming, so AGUI text
        # events fire exactly as they would with a real provider.
        if on_token and reply.text:
            for word in reply.text.split(" "):
                await on_token(word + " ")

        if on_tool_call:
            for tool_call in reply.tool_calls:
                await on_tool_call(tool_call)

        return Message(
            role="assistant",
            content=[TextContent(text=reply.text)],
            tool_calls=reply.tool_calls,
        )

    async def embed(self, model: str, text: str) -> list[float]:
        """A deterministic 3-dim vector — same text in, same vector out."""
        return [float(len(text)), float(sum(map(ord, text)) % 100), 1.0]

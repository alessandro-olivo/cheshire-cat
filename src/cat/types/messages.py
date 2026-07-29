from typing import List, Literal, Optional
from pydantic import BaseModel, computed_field

from ..protocols.model_context.type_wrappers import ContentBlock, TextContent, ToolCall


class Message(BaseModel):
    """Single Message exchanged between user and assistant, part of a conversation."""

    role: Literal["user", "assistant", "tool"]
    content: List[ContentBlock]

    tool_calls: List[ToolCall] = []
    """Only populated if the LLM wants to use a tool (role "assistant")."""

    tool_call_id: Optional[str] = None
    """Only populated for role="tool" messages."""

    structuredContent: Optional[dict] = None
    """Machine-readable structured output of an MCP tool result
    (`CallToolResult.structuredContent`). Preserved for UI/host consumption via the
    streamed tool-result event; never forwarded to LLM providers."""

    @classmethod
    def user(cls, text: str) -> "Message":
        """A user message from plain text — `Message.user("hello")`."""
        return cls(role="user", content=[TextContent(text=text)])

    @classmethod
    def assistant(cls, text: str) -> "Message":
        """An assistant message from plain text."""
        return cls(role="assistant", content=[TextContent(text=text)])

    @computed_field
    @property
    def text(self) -> str:
        """Concatenate all text blocks."""
        return "".join(
            block.text for block in self.content
            if hasattr(block, "text")
        )
"""
Core MCP-client primitives (no connection layer — that lives in the mcp plugin).

Covers:
- `Tool.from_fastmcp` populating UI metadata from `_meta.ui`
- visibility filtering: app-only tools excluded from the LLM tool list
- `standardize_output` preserving a `ui://` resource block (not degraded to text)
- `Message.structuredContent` preserved on the tool message but not leaked to providers
"""

from types import SimpleNamespace

import mcp.types as mt
from fastmcp.client.client import CallToolResult

from cat.mad_hatter.decorators.tool import Tool, ToolMeta
from cat.services.model_providers.openai_compatible import OpenAICompatibleProvider
from cat.types import Message, TextContent


async def _noop(name, args):  # stand-in MCP client function; never invoked here
    raise AssertionError("client function should not be called in these tests")


def _mcp_tool(name="widget", meta=None):
    return mt.Tool(name=name, inputSchema={"type": "object"}, _meta=meta)


# -- from_fastmcp UI metadata -------------------------------------------------

def test_from_fastmcp_populates_ui_metadata():
    t = _mcp_tool(meta={"ui": {"resourceUri": "ui://x", "visibility": ["model", "app"]}})
    tool = Tool.from_fastmcp(t, _noop)
    assert tool.meta.resource_uri == "ui://x"
    assert tool.meta.visibility == ["model", "app"]
    assert tool.meta.is_model_visible


def test_from_fastmcp_plain_tool_has_no_ui_metadata():
    tool = Tool.from_fastmcp(_mcp_tool(meta=None), _noop)
    assert tool.meta.resource_uri is None
    assert tool.meta.is_model_visible  # default = model-visible


def test_from_fastmcp_app_only_visibility():
    t = _mcp_tool(meta={"ui": {"resourceUri": "ui://x", "visibility": ["app"]}})
    tool = Tool.from_fastmcp(t, _noop)
    assert not tool.meta.is_model_visible


# -- visibility filtering when building the LLM tool list ---------------------

def _tool(name, visibility):
    return Tool(
        func=_noop, name=name, description=name,
        input_schema={"type": "object"}, output_schema=None,
        is_internal=False, meta=ToolMeta(visibility=visibility),
    )


def test_app_only_tool_excluded_from_llm_tools():
    provider = OpenAICompatibleProvider()
    tools = [
        _tool("visible", ["model"]),
        _tool("both", ["model", "app"]),
        _tool("app_only", ["app"]),
    ]
    names = {t["function"]["name"] for t in provider.build_tools(tools)}
    assert names == {"visible", "both"}
    assert "app_only" not in names


def test_default_tool_is_model_visible():
    # a plain @tool decorated function defaults to model-visible
    provider = OpenAICompatibleProvider()
    plain = Tool(
        func=_noop, name="plain", description="d",
        input_schema={"type": "object"}, output_schema=None,
    )
    names = {t["function"]["name"] for t in provider.build_tools([plain])}
    assert names == {"plain"}


# -- resource-block preservation & structuredContent --------------------------

def _standardize(tool_result):
    tool = Tool.from_fastmcp(_mcp_tool(), _noop)
    return tool.standardize_output(SimpleNamespace(id="call-1", args={}), tool_result)


def test_returned_ui_resource_block_is_preserved():
    embedded = mt.EmbeddedResource(
        type="resource",
        resource=mt.TextResourceContents(
            uri="ui://weather/forecast", text="<html/>", mimeType="text/html"
        ),
    )
    result = CallToolResult(content=[embedded], structured_content=None, meta=None)

    msg = _standardize(result)

    block = msg.content[0]
    assert block.type == "resource"                       # not degraded to text
    assert str(block.resource.uri) == "ui://weather/forecast"


def test_structured_content_preserved_on_tool_message():
    result = CallToolResult(
        content=[mt.TextContent(type="text", text="21°C")],
        structured_content={"temp": 21, "unit": "C"},
        meta=None,
    )

    msg = _standardize(result)

    assert msg.structuredContent == {"temp": 21, "unit": "C"}
    assert msg.text == "21°C"  # human-readable content also present


def test_tool_without_structured_output_has_none():
    result = CallToolResult(
        content=[mt.TextContent(type="text", text="plain")],
        structured_content=None,
        meta=None,
    )
    assert _standardize(result).structuredContent is None


async def test_structured_content_not_sent_to_provider():
    msg = Message(
        role="tool",
        content=[TextContent(text="21°C")],
        tool_call_id="call-1",
        structuredContent={"temp": 21},
    )
    payload = await OpenAICompatibleProvider().convert_message(msg)

    assert set(payload.keys()) == {"role", "tool_call_id", "content"}
    assert "structuredContent" not in payload

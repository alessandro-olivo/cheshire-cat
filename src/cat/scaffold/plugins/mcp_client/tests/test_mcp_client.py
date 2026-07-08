"""
mcp_client plugin tests — the connection layer core deliberately does not hold.

Covers:
- attaching the directive appends the server's tools + injects read_resource
- a tool call and read_resource work end-to-end (against an in-memory server)
- apikey auth becomes a bearer token on the client
- oauth2 is rejected with a clear error

The directive is exercised against an in-memory FastMCP server by swapping
`build_client` for one that connects to it — no network, no ports.
"""

import os
import sys
from types import SimpleNamespace

import pytest
from fastmcp import FastMCP, Client
from fastmcp.client.auth import BearerAuth

# Make the plugin package importable as `mcp_client.*` (the plugins/ root).
PLUGINS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PLUGINS_ROOT not in sys.path:
    sys.path.insert(0, PLUGINS_ROOT)

import mcp_client.directive as directive_module  # noqa: E402
from mcp_client.config import MCPServer, build_client  # noqa: E402
from mcp_client.directive import MCPDirective  # noqa: E402


@pytest.fixture
def in_memory_server(monkeypatch):
    """An in-memory MCP server; the directive connects to it via a patched build_client."""
    srv = FastMCP("Test")

    @srv.tool
    def add(a: int, b: int) -> int:
        """Add two numbers."""
        return a + b

    @srv.resource("ui://widget/card")
    def card() -> str:
        return "<html>card</html>"

    # every build_client(...) call yields a fresh client to the in-memory server
    monkeypatch.setattr(directive_module, "build_client", lambda server: Client(srv))
    return srv


async def _start(servers):
    directive = MCPDirective(servers=servers)
    agent = SimpleNamespace(tools=[])
    await directive.start(agent)
    return agent


# -- attaching adds tools -----------------------------------------------------

async def test_attaching_adds_server_tools_and_read_resource(in_memory_server):
    agent = await _start([MCPServer(name="t", url="http://unused")])
    names = [t.name for t in agent.tools]
    assert "add" in names
    assert "read_resource" in names


async def test_attached_tool_is_callable(in_memory_server):
    agent = await _start([MCPServer(name="t", url="http://unused")])
    add_tool = next(t for t in agent.tools if t.name == "add")
    result = await add_tool.func("add", {"a": 2, "b": 3})
    assert result.content[0].text == "5"


# -- read_resource ------------------------------------------------------------

async def test_read_resource_returns_content_blocks(in_memory_server):
    agent = await _start([MCPServer(name="t", url="http://unused")])
    read_resource = next(t for t in agent.tools if t.name == "read_resource")

    msg = await read_resource.func(uri="ui://widget/card")

    block = msg.content[0]
    assert block.type == "resource"
    assert str(block.resource.uri) == "ui://widget/card"


async def test_read_resource_unknown_uri_returns_error(in_memory_server):
    agent = await _start([MCPServer(name="t", url="http://unused")])
    read_resource = next(t for t in agent.tools if t.name == "read_resource")

    result = await read_resource.func(uri="ui://does/not/exist")

    assert isinstance(result, str)
    assert "Error" in result


# -- auth ---------------------------------------------------------------------

def test_apikey_becomes_bearer_auth():
    server = MCPServer(name="secured", url="https://api.example/mcp",
                       auth_type="apikey", token="sk-secret")
    client = build_client(server)
    assert isinstance(client.transport.auth, BearerAuth)


def test_none_auth_has_no_authorization():
    server = MCPServer(name="open", url="https://api.example/mcp", auth_type="none")
    client = build_client(server)
    assert client.transport.auth is None


def test_apikey_without_token_is_rejected():
    with pytest.raises(ValueError, match="requires a token"):
        MCPServer(name="bad", url="https://api.example/mcp",
                  auth_type="apikey").to_remote()


def test_oauth2_is_rejected():
    with pytest.raises(ValueError, match="not supported yet"):
        MCPServer(name="oauth", url="https://api.example/mcp",
                  auth_type="oauth2").to_remote()

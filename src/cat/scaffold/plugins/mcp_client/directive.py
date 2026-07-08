"""
The MCP directive — attach MCP servers' tools to an agent, statelessly.

Attach it to an agent to make the configured servers' tools callable by the LLM:

    from mcp_client.directive import MCPDirective
    from mcp_client.config import MCPServer

    class ResearchAgent(Agent):
        directives = [MCPDirective(servers=[
            MCPServer(name="weather", url="https://weather.example/mcp"),
        ])]

Or attach by slug (`directives = ["mcp"]`) and configure the server list in the
plugin settings.

How it stays stateless: `start(agent)` opens a short-lived client only to *list*
each server's tools, then closes it. Each resulting tool carries its own per-call
closure that opens a fresh client for that one `tools/call` and closes it again —
no pool, no session kept between calls or runs. `finish(agent)` has nothing to
tear down.
"""

from cat import Directive, Agent, log
from cat.mad_hatter.decorators import Tool
from cat.types import Message

from .config import Settings as MCPSettings, build_client


class MCPDirective(Directive):
    slug = "mcp"
    name = "MCP"
    description = "Connects MCP servers statelessly and adds their tools to an agent."

    # Typed settings (the server list) live in config.py; expose them as the
    # service's stored shape so `load_settings()` and the settings UI pick them up.
    Settings = MCPSettings

    def __init__(self, servers=None):
        # `servers` set inline (per-agent attachment) overrides the saved settings.
        # Left None, the directive composes its server list from settings at run time.
        self._servers_override = servers

    async def _composed_servers(self):
        """Which servers to connect for this run.

        Composition points (all optional):
        - per-agent  → the directive instance's `servers=` (which directive is attached)
        - saved      → plugin settings' server list
        A subclass may also read `from cat import user` (or the current chat) here to
        scope per-user / per-chat before returning the list.
        """
        if self._servers_override is not None:
            return self._servers_override
        settings = await self.load_settings()
        return settings.servers if settings else []

    async def start(self, agent: Agent) -> None:
        servers = await self._composed_servers()
        if not servers:
            return

        for server in servers:
            try:
                async with build_client(server) as client:
                    mcp_tools = await client.list_tools()
            except Exception as e:
                log.error(f"MCP directive: could not connect to '{server.name}': {e}")
                continue

            for t in mcp_tools:
                agent.tools.append(Tool.from_fastmcp(t, self._call_tool_func(server, t.name)))

        # One resource reader across all connected servers.
        agent.tools.append(self._read_resource_tool(servers))

    async def finish(self, agent: Agent) -> None:
        # Stateless: no pooled sessions to close.
        pass

    def _call_tool_func(self, server, tool_name):
        """A stateless per-call function bound to one server + tool.

        Opens a fresh client for this single `tools/call` and closes it. The
        original tool name is captured so the call is correct regardless of how the
        Cat labels the tool.
        """
        async def call(_name, args):
            async with build_client(server) as client:
                return await client.call_tool(tool_name, args)
        return call

    def _read_resource_tool(self, servers) -> Tool:
        """Build the injected `read_resource(uri)` internal tool."""

        async def read_resource(uri: str):
            """Read an MCP resource by its URI and return its contents."""
            for server in servers:
                try:
                    async with build_client(server) as client:
                        contents = await client.read_resource(uri)
                except Exception:
                    continue  # this server doesn't have it (or errored) — try the next
                if contents:
                    blocks = [
                        {"type": "resource", "resource": rc.model_dump()}
                        for rc in contents
                    ]
                    return Message(role="tool", content=blocks)
            # Graceful error result — never aborts the agent run.
            return f"Error: no connected MCP server exposes resource {uri!r}"

        return Tool.from_decorated_function(read_resource)

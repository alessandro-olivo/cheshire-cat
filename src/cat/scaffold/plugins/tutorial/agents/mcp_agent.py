"""
An agent whose tools come from an MCP server — attached as a directive.

The lesson of `time_aware_agent` was "a directive is middleware you attach." This
is the same idea, one step bigger: **a whole MCP server is just a directive too.**

The Cheshire Cat speaks the Model Context Protocol as a *stateless client*. It
never runs an MCP server and keeps no session — every tool call is an independent
request. All the connection plumbing lives in the `mcp_client` plugin, which
exposes an `mcp` directive. Attach it and, during the agent's `start()`, the
directive connects the configured server(s), turns each of their tools into a
normal Cat tool on `agent.tools`, and injects a `read_resource(uri)` tool. From
the loop's point of view they are ordinary tools — the LLM calls them like any
other.

Two ways to choose the servers:

1. **By slug (used here).** `directives = ["mcp"]` picks up the server list from
   the `mcp_client` plugin settings. Configure servers once, share them across
   agents. (Requires the `mcp_client` plugin installed and at least one server
   configured — otherwise this agent has only the injected `read_resource` tool.)

2. **Inline, per agent.** Import the directive and hand it its own servers, so the
   server set *is* the attachment:

       from mcp_client.directive import MCPDirective
       from mcp_client.config import MCPServer

       directives = [MCPDirective(servers=[
           MCPServer(name="weather", url="https://weather.example/mcp"),
           MCPServer(name="internal", url="https://api.acme.com/mcp",
                     auth_type="apikey", token="sk-..."),
       ])]

Either way the agent's code below stays empty of MCP details — that is the point.
Scoping falls out for free: which agent attaches the directive (per-agent), and
the directive itself can read `from cat import user` to pick servers per user.
"""

from cat import Agent


class MCPAgent(Agent):
    slug = "mcp_agent"
    name = "MCP Agent"
    description = "An agent whose tools are served by an MCP server, attached via the mcp directive."

    # A whole MCP server, attached like any other directive. The server list comes
    # from the mcp_client plugin settings; see the module docstring for the inline
    # per-agent form.
    directives = ["mcp"]

    system_prompt = (
        "You are a helpful assistant. Some of your tools are provided by external "
        "MCP servers — use them to answer the user instead of guessing. If you need "
        "a resource behind a `ui://` or other URI, call `read_resource` to fetch it."
    )

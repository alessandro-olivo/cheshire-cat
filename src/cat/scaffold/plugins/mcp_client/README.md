# MCP Client

Attach [Model Context Protocol](https://modelcontextprotocol.io) servers to an agent. The Cat is a **stateless MCP client**: every `tools/call` and `resources/read` is an independent request — no session, no connection pool.

All the transport/connection plumbing lives here in the plugin. Core only knows about tools and messages.

## Attach it to an agent

Inline (per-agent, the server list is the attachment):

```python
from cat import Agent
from mcp_client.directive import MCPDirective
from mcp_client.config import MCPServer

class ResearchAgent(Agent):
    directives = [MCPDirective(servers=[
        MCPServer(name="weather", url="https://weather.example/mcp"),
        MCPServer(name="internal", url="https://api.acme.com/mcp",
                  auth_type="apikey", token="sk-..."),
    ])]
```

Or by slug, configuring the server list in the plugin settings:

```python
class ResearchAgent(Agent):
    directives = ["mcp"]
```

## What attaching does

During the directive's `start(agent)`:

1. Connects each configured server (statelessly) and **appends its tools** to `agent.tools`. Each tool carries its MCP `_meta.ui` metadata (`resourceUri`, `visibility`); app-only tools are kept out of what the LLM sees.
2. Injects a **`read_resource(uri)`** tool that performs `resources/read` across the connected servers and returns the contents as content blocks. An unknown URI returns an error result rather than aborting the run.

## Auth

| `auth_type` | behavior                                   |
|-------------|--------------------------------------------|
| `none`      | no authorization header                    |
| `apikey`    | `token` sent as a bearer header per request|
| `oauth2`    | **rejected** — not supported yet           |

## Scoping

- **Per agent** — which directive (and server list) is attached.
- **Per user / per chat** — subclass `MCPDirective` and override `_composed_servers()` to read `from cat import user` (or the current chat) and pick servers accordingly.

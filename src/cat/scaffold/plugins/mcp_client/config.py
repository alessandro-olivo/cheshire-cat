"""
MCP server configuration for the mcp_client plugin.

Core holds no MCP config type — all transport/connection plumbing lives here. An
`MCPServer` is the plugin's own config shape; it converts to a fastmcp
`RemoteMCPServer` and, from there, to a stateless `Client`.

Auth: only `none` and `apikey` (bearer token) are supported. `oauth2` is rejected
with a clear error until a later change adds it.
"""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field
from fastmcp import Client
from fastmcp.client.auth import BearerAuth
from fastmcp.mcp_config import RemoteMCPServer


AuthType = Literal["none", "apikey", "oauth2"]


class MCPServer(BaseModel):
    """A single MCP server the Cat connects to as a stateless client."""

    name: str = Field(description="Short label; namespaces this server's tools.")
    url: str = Field(description="The server's MCP endpoint URL.")
    auth_type: AuthType = "none"
    token: Optional[str] = Field(
        default=None,
        description="Bearer token, required when auth_type = 'apikey'.",
    )

    def to_remote(self) -> RemoteMCPServer:
        """Convert to a fastmcp RemoteMCPServer, applying auth.

        Raises ValueError for the unsupported `oauth2` mode so a misconfiguration
        fails loudly instead of silently connecting without auth.
        """
        if self.auth_type == "oauth2":
            raise ValueError(
                f"MCP server '{self.name}': oauth2 auth is not supported yet. "
                "Use auth_type 'none' or 'apikey'."
            )

        auth = None
        if self.auth_type == "apikey":
            if not self.token:
                raise ValueError(
                    f"MCP server '{self.name}': auth_type 'apikey' requires a token."
                )
            auth = BearerAuth(token=self.token)

        return RemoteMCPServer(url=self.url, auth=auth)


def build_client(server: MCPServer) -> Client:
    """A fresh, stateless fastmcp Client for one server.

    Statelessness by construction: a new Client per use, no pool, no cached
    session. Callers open it with `async with` for the duration of a single
    request and let it close.
    """
    return Client(server.to_remote().to_transport())


class Settings(BaseModel):
    """Typed settings for the MCP directive: the servers to attach."""

    servers: List[MCPServer] = Field(
        default_factory=list,
        description="MCP servers whose tools this directive adds to an agent.",
    )

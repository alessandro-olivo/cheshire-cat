"""
The `cat` package — the front door.

`cat` means exactly one thing: this package. There is no userspace `cat`
instance to thread around. You don't import capabilities and hold them; you
import *names* whose behaviour is resolved, per call, against the configured
installation:

    from cat import log, tool, endpoint, hook, config, user, store, llm

Four modules, one job each — that is the whole import surface:

    cat          build an agent    log tool endpoint hook execute_hook config
                                   user store plugin agui_event
                                   llm embedder get get_all call_agent
                                   Agent Directive

    cat.types    data you pass     Message Task TaskResult Tool
                                   TextContent ImageContent AudioContent ...

    cat.base     extend the        Service ModelProvider Auth User
                 framework         OpenAICompatibleProvider

    cat.db       persist           store Store UserStore UserScopedDB

**`cat` to build, `cat.types` to speak, `cat.base` to extend, `cat.db` to
persist.** A plugin that only defines agents and tools imports from `cat` and
nothing else; nothing needs an import deeper than these four.

`cat` holds only names you *call or read* — not names you subclass. `Agent` and
`Directive` are the one deliberate exception, re-exported from `cat.base`
because you subclass them in your first five minutes. Names are ordered below by
how often plugins actually reach for them, most-used first.
"""

# --- building blocks (most used) -------------------------------------------
# (config is imported before log because log reads it at construction time;
#  __all__ below is ordered by usage frequency, not import order.)
from .config import config
from .log import log
from .mad_hatter.decorators import tool, endpoint
from .ambient import hook, execute_hook

# --- ambient request context -----------------------------------------------
from .ambient.context_vars import user
from .db import store
from .ambient.runtime import plugin
from .ambient import agui_event

# --- models & agents -------------------------------------------------------
from .ambient import llm, embedder
from .services.agents.base import Agent
from .services.directives.base import Directive

# --- registry escape hatch -------------------------------------------------
from .ambient import get, get_all, call_agent

__all__ = [
    # building blocks (most used)
    "log",
    "tool",
    "endpoint",
    "hook",
    "execute_hook",
    "config",
    # ambient request context
    "user",
    "store",
    "plugin",
    "agui_event",
    # models & agents
    "llm",
    "embedder",
    "Agent",
    "Directive",
    # registry escape hatch
    "get",
    "get_all",
    "call_agent",
]

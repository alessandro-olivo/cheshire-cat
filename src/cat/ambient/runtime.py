"""
The single CheshireCat instance per process.

`ccat()` returns the one running instance; `set_ccat()` registers it once at
bootstrap (see `CheshireCat.bootstrap`). A plain module global, not a contextvar
— there is exactly one cat per process, shared by every request.

Internal plumbing behind the `cat` package front door: user code never names
`ccat()`, it reaches ambient state with `from cat import ...`. The per-request
context lives in `cat.ambient.context_vars`.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cat.looking_glass.cheshire_cat import CheshireCat


_ccat: "CheshireCat | None" = None


def ccat() -> "CheshireCat":
    """Return the one CheshireCat instance. Internal usage only."""
    if _ccat is None:
        raise RuntimeError("CheshireCat is not bootstrapped yet.")
    return _ccat


def set_ccat(instance: "CheshireCat") -> None:
    """Register the process-wide CheshireCat instance (called at bootstrap)."""
    global _ccat
    _ccat = instance


# Which plugin's code is currently executing. Set by the framework wherever it
# dispatches into a plugin (endpoint handler, hook, tool), reset on the way out.
# A contextvar rather than a call-stack walk: frames lie once a decorator or a
# wrapper sits between the framework and the plugin function, and each asyncio
# Task gets its own copy so concurrent requests never see each other's plugin.
_plugin_id: ContextVar["str | None"] = ContextVar("cat_plugin_id", default=None)


@contextmanager
def use_plugin(plugin_id: "str | None"):
    """Mark the plugin owning the code about to run (set + reset)."""
    token = _plugin_id.set(plugin_id)
    try:
        yield
    finally:
        _plugin_id.reset(token)


class _PluginProxy:
    """Live proxy to the plugin that owns the calling code.

    `from cat import plugin` binds this once; every attribute read resolves the
    plugin whose code is currently executing. Lets plugin code reach its own
    metadata/path — `plugin.path` — without importing the cat handle or
    threading `self`.
    """

    def _plugin(self):
        plugin_id = _plugin_id.get()
        if plugin_id is None:
            raise RuntimeError(
                "`plugin` is only available inside plugin code the framework "
                "dispatched into — an endpoint handler, a hook, or a tool. "
                "It cannot be read at import time or from core."
            )
        return ccat().mad_hatter.plugins[plugin_id]

    def __getattr__(self, name):
        return getattr(self._plugin(), name)

    def __repr__(self):
        plugin_id = _plugin_id.get()
        if plugin_id is None:
            return "<cat.plugin (outside plugin code)>"
        return f"<cat.plugin {plugin_id}>"


plugin = _PluginProxy()

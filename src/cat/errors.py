"""
Errors the framework raises at plugin authors.

Three names, no hierarchy beyond `CatError`, no error codes. The point is not
taxonomy for its own sake — it is that a message tells you *what happened, why,
and what to do*, and that an agent reading the traceback can branch on the type.

    PluginError     — a plugin is wired wrong (bad declaration, missing piece)
    ServiceNotFound — asked the registry for something that is not registered
    HookError       — a hook was defined or fired wrongly
"""


class CatError(Exception):
    """Base for every error the framework raises at plugin code."""


class PluginError(CatError):
    """A plugin is declared or wired incorrectly."""


class ServiceNotFound(CatError):
    """A service was requested by type+slug and is not registered.

    Carries the available slugs, so the message can say what *is* there.
    """

    def __init__(self, type: str, slug: str, available: "list[str] | None" = None):
        self.type = type
        self.slug = slug
        self.available = sorted(available or [])

        known = ", ".join(self.available) if self.available else "none registered"
        message = (
            f"Service of type '{type}' and slug '{slug}' not found. "
            f"Registered {type}: {known}."
        )
        if suggestion := _did_you_mean(slug, self.available):
            message += f" Did you mean '{suggestion}'?"
        super().__init__(message)


class HookError(CatError):
    """A hook was defined or fired incorrectly."""


def _did_you_mean(name: str, candidates: "list[str]") -> "str | None":
    """Closest candidate to `name`, if one is close enough to be worth saying."""
    from difflib import get_close_matches

    matches = get_close_matches(name, candidates, n=1, cutoff=0.7)
    return matches[0] if matches else None

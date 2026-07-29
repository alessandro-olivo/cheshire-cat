from typing import Callable
from fastapi import APIRouter


class Endpoint(APIRouter):

    def __repr__(self) -> str:
        if hasattr(self, 'plugin_id'):
            plugin = self.plugin_id # will be added by mad hatter
        else:
            plugin = "unknown"
        return f"Endpoint(plugin={plugin} routes={self.routes})"


# Endpoints are collected off the module namespace, so two decorated functions
# sharing a name in one module silently lose one route — the second binding
# shadows the first. We cannot see the loss at collection time (the shadowed
# router is already unreachable), so we catch it at decoration time instead.
# Key is (module, function name) → (method, path); a re-import re-registers the
# identical entry and is fine, a different path under the same name is the bug.
_DECLARED: dict[tuple[str, str], tuple[str, str]] = {}


def forget_module(module_name: str) -> None:
    """Drop a module's recorded endpoint names, before it is (re)imported.

    Called by the plugin loader on every import so that editing a path and
    reloading the plugin is not mistaken for a name collision.
    """
    for key in [k for k in _DECLARED if k[0] == module_name]:
        del _DECLARED[key]


class EndpointDecorator:
    """Sugar for plugin HTTP endpoints.

    A plugin never touches FastAPI's `Depends` or any auth helper. Reading the
    user is ambient (`from cat import user`); gating by role is a single kwarg:

        from cat import endpoint, user

        @endpoint.get("/public")                       # open
        async def public(): ...

        @endpoint.get("/me", role="authenticated")     # any logged-in user
        async def me(): return {"hi": user.name}

        @endpoint.get("/admin", role="admin")          # requires "admin"
        async def admin(): ...

        @endpoint.get("/staff", role=["admin", "editor"])  # any of these (OR)
        async def staff(): ...

    `role` semantics:
      - None (default)      → open, no auth required.
      - "authenticated"     → any logged-in user, regardless of roles.
      - "admin"             → must have that role.
      - ["a", "b"]          → must have any of these (OR).

    Any non-None `role` injects the same auth dependency core uses
    (`cat.auth.depends._get_user`), which 403s when the caller is unauthenticated
    or lacks the role. Other kwargs (`prefix`, `tags`, `response_model`, ...) pass
    straight to FastAPI.
    """

    def _wrap(self, method: str, path: str, **kwargs):

        def decorator(func: Callable):

            prefix = kwargs.pop("prefix", "")
            full_path = f"{prefix}{path}"

            # `role=` sugar → inject the core auth dependency. Imported lazily to
            # avoid an import cycle (this module is imported at `cat` boot).
            role = kwargs.pop("role", None)
            dependencies = list(kwargs.pop("dependencies", []))
            if role is not None:
                from cat.auth.depends import _get_user
                dependencies.append(_get_user(role=role))

            key = (getattr(func, "__module__", "?"), func.__name__)
            declared = (method.upper(), full_path)
            previous = _DECLARED.get(key)
            if previous is not None and previous != declared:
                raise ValueError(
                    f"Two endpoints in {key[0]} are both named '{func.__name__}': "
                    f"{previous[0]} {previous[1]} and {declared[0]} {declared[1]}. "
                    "Endpoints are collected by function name, so the second would "
                    "silently replace the first — give them different names."
                )
            _DECLARED[key] = declared

            router = Endpoint()
            router.add_api_route(
                path=full_path,
                endpoint=func,
                methods=[method.upper()],
                dependencies=dependencies,
                **kwargs
            )

            return router
        return decorator

    def get(self, path: str, **kwargs):
        return self._wrap("get", path, **kwargs)

    def post(self, path: str, **kwargs):
        return self._wrap("post", path, **kwargs)

    def put(self, path: str, **kwargs):
        return self._wrap("put", path, **kwargs)

    def patch(self, path: str, **kwargs):
        return self._wrap("patch", path, **kwargs)

    def delete(self, path: str, **kwargs):
        return self._wrap("delete", path, **kwargs)
    
    def router(self, function: Callable):

        # TODOV2: support async functions
        returned_router = function()

        if not isinstance(returned_router, APIRouter):
            raise TypeError(
                "The function decorated with @endpoint.router must return an APIRouter instance."
            )

        ce = Endpoint()
        ce.include_router(returned_router)
        return ce

endpoint = EndpointDecorator()
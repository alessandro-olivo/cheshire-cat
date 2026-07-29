"""
Cheshire Cat test harness — the one primitive plugin authors and core share.

Shipped as a pytest plugin via a ``pytest11`` entry point (see pyproject.toml),
so the core suite *and* every plugin suite get the same fixtures with no conftest
duplication. Install cheshire-cat-ai, drop tests under ``plugins/<name>/tests/``,
run ``pytest`` — the fixtures and the ``with_plugins`` marker are just there.

The one primitive — "core plus these plugins":

    # core test (under tests/): core only, zero plugins active
    def test_core(client): ...

    # core test that needs a plugin
    @pytest.mark.with_plugins("uploads")
    def test_uploads(client): ...

    # plugin test (under plugins/<name>/tests/): core + that plugin, auto-included
    def test_my_plugin(client): ...

    # plugin test that also wants a sibling on top of itself
    @pytest.mark.with_plugins("chats")
    def test_my_plugin_with_chats(client): ...

Two invariants hold for every test:

- **Per-test isolation** — each test runs in a throwaway project folder (project
  path, ``data/``, ``uploads/``, ``plugins/`` and the SQLite db all repointed into
  ``tmp_path`` and scaffolded fresh). The developer's real ``./data`` and
  ``./plugins`` are never read for assertions nor mutated by a test.
- **One plugin source of truth** — selected plugins are resolved from the project
  ``./plugins`` folder only, never from the ``scaffold/`` package. A dev-only
  plugin (one that lives solely in ``./plugins``) is selectable exactly like a
  shipped one.
"""

import os
import shutil
from typing import Any, Generator
from uuid import UUID

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cat import config
from cat.mad_hatter.plugin import Plugin
from cat.db.database import DB as db_engine


# ---------------------------------------------------------------------------
# Roots captured ONCE at import (session start), before any test repoints
# `config`. This is the developer's real project root — the single source of
# truth for plugins in tests: tests read `./plugins`, never `scaffold/`.
# ---------------------------------------------------------------------------
REPO_PLUGINS = os.path.abspath(config.PLUGINS_PATH)
SCAFFOLD_PLUGINS = os.path.join(config.BASE_PATH, "scaffold", "plugins")


def pytest_configure(config):
    """Register the marker and materialize `./plugins` once per session.

    Materialization is the only point where `scaffold/` meets the tests: it
    seeds the project `./plugins` with the vendored default plugins so a shipped
    plugin's tests (authored under `scaffold/plugins/<name>/tests/`) reach
    `./plugins/<name>/tests/` and get collected. It is idempotent — a plugin
    folder already present in `./plugins` is left untouched, so the developer's
    own plugins are never overwritten.
    """
    config.addinivalue_line(
        "markers",
        "with_plugins(*names): boot core plus the named plugins for this test "
        "(resolved from ./plugins). In a plugin's own tests/, the owning plugin "
        "is auto-included and these names are added on top.",
    )

    # Async tests just work: a plugin author writes `async def test_...()` with no
    # marker and no config. The Cat is async to the core, so its tests are too — we
    # make `asyncio_mode = "auto"` the default here (unless the project explicitly
    # sets its own mode) so nobody has to remember `@pytest.mark.asyncio` or add
    # pytest config to a fresh install. `getoption` is honored first, so a
    # deliberate `--asyncio-mode`/`-o asyncio_mode=...` still wins.
    if config.getoption("asyncio_mode", None) is None and "asyncio_mode" not in config.inicfg:
        config.inicfg["asyncio_mode"] = "auto"
        config._inicache.pop("asyncio_mode", None)  # drop any cached "strict" read

    if os.path.isdir(SCAFFOLD_PLUGINS):
        os.makedirs(REPO_PLUGINS, exist_ok=True)
        for name in os.listdir(SCAFFOLD_PLUGINS):
            src = os.path.join(SCAFFOLD_PLUGINS, name)
            dst = os.path.join(REPO_PLUGINS, name)
            if os.path.isdir(src) and not os.path.exists(dst):
                shutil.copytree(src, dst)


def _owning_plugin(node) -> str | None:
    """The plugin a test belongs to, inferred from its path.

    A test under `<REPO_PLUGINS>/<name>/tests/...` is owned by `<name>`; that
    plugin is auto-included so a plugin's tests never have to name themselves.
    Core tests (under `tests/`) have no owning plugin.
    """
    test_path = os.path.abspath(str(node.path))
    if test_path.startswith(REPO_PLUGINS + os.sep):
        return os.path.relpath(test_path, REPO_PLUGINS).split(os.sep)[0]
    return None


def _selected_plugins(request) -> set[str]:
    """Resolve the plugin set for a test: owning plugin (if any) + marker names."""
    selected: set[str] = set()
    owner = _owning_plugin(request.node)
    if owner:
        selected.add(owner)
    marker = request.node.get_closest_marker("with_plugins")
    if marker:
        selected.update(marker.args)
    return selected


def _set_active_plugins(names) -> None:
    """Seed the DB `active_plugins` setting (sync, before app bootstrap)."""
    from cat.db.models import KeyValueDB

    setting = (
        KeyValueDB.objects().where(KeyValueDB.key == "active_plugins").first().run_sync()
    )
    if setting is None:
        setting = KeyValueDB(key="active_plugins", value=list(names))
    else:
        setting.value = list(names)
    setting.save().run_sync()


@pytest.fixture(scope="function", autouse=True)
def isolated_project(monkeypatch, tmp_path, request):
    """Fresh, isolated project per test, with the selected plugins active.

    Repoints every project path and the SQLite engine into `tmp_path`, scaffolds
    a clean project, then imposes the resolved plugin selection inside it:
    `./plugins` in the tmp project is reduced to exactly the selected plugins
    (copied from the developer's real `./plugins`, never from `scaffold/`) and
    `active_plugins` is seeded to that set. Unmarked core test → zero plugins.
    """
    mocks = tmp_path / "mocks"
    monkeypatch.setitem(config._values, "PROJECT_PATH", str(mocks))
    monkeypatch.setitem(config._values, "PLUGINS_PATH", str(mocks / "plugins"))
    monkeypatch.setitem(config._values, "DATA_PATH", str(mocks / "data"))
    monkeypatch.setitem(config._values, "UPLOADS_PATH", str(mocks / "data" / "uploads"))

    # do not check plugin dependencies on every (re)install during tests
    monkeypatch.setattr(Plugin, "_install_requirements", lambda self, *a, **k: None)

    # point the process-wide SQLite engine at this test's own db file
    monkeypatch.setattr(db_engine, "path", str(mocks / "data" / "core" / "core.db"))

    # scaffold the fresh project (folders + db/tables + seeded settings)
    from cat.scaffold import scaffolder

    scaffolder.setup_project()

    # impose the plugin selection inside the pristine tmp project
    selected = _selected_plugins(request)
    tmp_plugins = str(mocks / "plugins")

    # strict isolation: clear whatever the scaffolder copied in, then re-copy
    # ONLY the selected plugins, resolved from the developer's real ./plugins
    if os.path.isdir(tmp_plugins):
        for name in os.listdir(tmp_plugins):
            p = os.path.join(tmp_plugins, name)
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)
    for name in selected:
        src = os.path.join(REPO_PLUGINS, name)
        if not os.path.isdir(src):
            raise RuntimeError(
                f"Selected plugin '{name}' not found in {REPO_PLUGINS}. "
                "with_plugins() resolves plugins from ./plugins only."
            )
        shutil.copytree(src, os.path.join(tmp_plugins, name))

    # seed active_plugins to exactly the selected set
    _set_active_plugins(sorted(selected))


# The default master key ("meow") as a Bearer header. Baked into the standard
# clients so the common case — an authenticated admin — needs no boilerplate.
ADMIN_HEADERS = {"Authorization": "Bearer meow"}

# Identity `run_agent` uses when a test doesn't pass one. Fixed, so user-scoped
# writes are readable across calls within a test.
TEST_USER_ID = UUID("00000000-0000-0000-0000-00000000ca7a")


####################################
# Main fixture for the FastAPI app #
####################################
@pytest.fixture(scope="function")
def app() -> Generator[FastAPI, Any, None]:
    # a fresh app per test (isolated routes + lifespan); see startup.create_app
    from cat.startup import create_app

    yield create_app()


##############################
# Sync version of the client #
##############################
@pytest.fixture(scope="function")
def client(app) -> Generator[TestClient, Any, None]:
    """TestClient authenticated as admin by default (master key in every request).

    Override per request with `headers=...` (e.g. a JWT for another user), or use
    the `anon_client` fixture for unauthenticated calls.
    """
    with TestClient(app, headers=ADMIN_HEADERS) as client:
        yield client


@pytest.fixture(scope="function")
def anon_client(app) -> Generator[TestClient, Any, None]:
    """TestClient with no credentials — for testing public routes and auth gating.

    Pass `headers={"Authorization": f"Bearer {credential}"}` per request to
    authenticate as a specific key/JWT.
    """
    with TestClient(app) as client:
        yield client


###############################
# Async version of the client #
###############################
@pytest.fixture(scope="function")
async def async_client(booted_app):
    """Async client authenticated as admin by default (see `client`)."""
    async with AsyncClient(
        transport=ASGITransport(app=booted_app), base_url="http://test", headers=ADMIN_HEADERS
    ) as ac:
        yield ac


#############################################
# In-process agent runs (no server, no HTTP) #
#############################################
@pytest.fixture(scope="function")
async def booted_app(app):
    """The app with its lifespan run — i.e. a bootstrapped CheshireCat.

    Everything that resolves services (`fake_llm`, `run_agent`) needs the cat
    bootstrapped; the HTTP clients need it too, and get it through this.
    """
    async with LifespanManager(app):
        yield app


@pytest.fixture(scope="function")
async def fake_llm(booted_app):
    """A programmable LLM, wired in as the installation's default model.

    Script its replies, run an agent, then assert on what the provider received:

        async def test_agent(fake_llm, run_agent):
            fake_llm.reply_text("hello")
            result = await run_agent("default", "hi")
            assert result.messages[-1].text == "hello"
            assert fake_llm.calls[0].messages[-1].text == "hi"

    See `cat.testing.fake_llm` for the full scripting API.
    """
    from cat.ambient.runtime import ccat
    from cat.testing.fake_llm import FakeModelProvider

    # A singleton service caches its instance on the class; that cache outlives
    # the test, so clear it before and after to keep runs independent.
    await FakeModelProvider.refresh()

    ccat().registry.register(FakeModelProvider)
    provider = await ccat().get("model_providers", FakeModelProvider.slug)

    # make it the configured default, the way a user would in the settings UI
    core = await ccat().get("config", "core")
    settings = await core.load_settings()
    settings.default_llm = f"{FakeModelProvider.slug}:fake"
    settings.default_embedder = f"{FakeModelProvider.slug}:fake"
    await core.save_settings(settings)

    yield provider

    await FakeModelProvider.refresh()


@pytest.fixture(scope="function")
async def run_agent(booted_app):
    """Run an agent in-process: no server, no HTTP, no SSE.

    `await run_agent("todo", "buy milk")` builds the request context (with an
    admin test user, so ambient `user` resolves inside tools) and dispatches
    through the same `call_agent` any plugin would use.

    Pass a `Task` instead of a string when you need resources, args or history.
    """
    from cat.ambient import call_agent
    from cat.ambient.context_vars import Ctx, use_ctx
    from cat.auth.user import User
    from cat.types import Message, Task, TextContent

    # A stable id, so user-scoped data written by one call is readable by the
    # next within a test (each test still gets a fresh db).
    default_user = User(id=TEST_USER_ID, name="test", roles=["admin"])

    async def _run(slug: str, task: "str | Task", user: "User | None" = None):
        if isinstance(task, str):
            task = Task(
                messages=[Message(role="user", content=[TextContent(text=task)])],
                stream=False,
            )
        with use_ctx(Ctx(user=user or default_user)):
            return await call_agent(slug, task)

    return _run

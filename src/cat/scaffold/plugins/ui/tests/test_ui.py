"""ui plugin suite.

Its handlers read `plugin.path` — the ambient `plugin` proxy — from inside a
FastAPI route, which is the case that stack-walking got wrong once a wrapper sat
between the framework and the handler.
"""


def test_index_is_served(anon_client):
    """`plugin.path` resolves inside the handler, so index.html is found."""
    response = anon_client.get("/")
    assert response.status_code == 200
    assert "<html" in response.text.lower()


def test_asset_traversal_is_forbidden(anon_client):
    """The assets guard rejects an escape from the dist/assets root."""
    response = anon_client.get("/assets/%2e%2e/index.html")
    assert response.status_code == 403


def test_missing_asset_is_404(anon_client):
    assert anon_client.get("/assets/nope.js").status_code == 404

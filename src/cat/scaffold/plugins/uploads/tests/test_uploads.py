"""Uploads plugin suite.

Lives in the plugin, so the harness auto-includes `uploads` (core + uploads) for
every test here — no need to name the plugin. The uploads endpoints are mounted
under `/uploads`.
"""

import os


from cat import config


def test_serve_nonexistent_file(client):
    """GET a file that isn't there → 404 (serving endpoint is open)."""
    response = client.get("/uploads/Meooow.txt")
    assert response.status_code == 404


def test_serve_existing_file(client):
    """A file present under UPLOADS_PATH is served back."""
    file_name = "Meooow.txt"
    file_path = os.path.join(config.UPLOADS_PATH, file_name)

    # before: not there
    assert client.get(f"/uploads/{file_name}").status_code == 404

    os.makedirs(config.UPLOADS_PATH, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("Meow")

    response = client.get(f"/uploads/{file_name}")
    assert response.status_code == 200
    assert response.text == "Meow"


def test_upload_then_list(client):
    """Upload a file, then it shows up in the per-user listing."""
    files = {"file": ("hello.txt", b"hello cat", "text/plain")}
    response = client.post("/uploads", files=files)
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["mime_type"] == "text/plain"
    assert "uploads/" in body["url"]
    assert body["url"].startswith(config.URL)

    # it appears in the authenticated user's upload listing
    listing = client.get("/uploads")
    assert listing.status_code == 200
    assert any(u["url"].endswith("hello.txt") for u in listing.json())


def test_listing_includes_dotfiles_and_extensionless(client):
    """`**.*` used to skip both; the listing must show every file."""
    for name in (".hidden", "README", "plain.txt"):
        files = {"file": (name, b"meow", "text/plain")}
        assert client.post("/uploads", files=files).status_code == 200, name

    urls = [u["url"] for u in client.get("/uploads").json()]
    for name in (".hidden", "README", "plain.txt"):
        assert any(u.endswith(name) for u in urls), f"{name} missing from listing"


def test_upload_requires_authentication(anon_client):
    """Anonymous upload → 403, not the 500 the ambient `user` proxy used to raise."""
    files = {"file": ("hello.txt", b"hello cat", "text/plain")}
    assert anon_client.post("/uploads", files=files).status_code == 403


def test_listing_requires_authentication(anon_client):
    """Anonymous listing → 403 (the listing is per-user)."""
    assert anon_client.get("/uploads").status_code == 403


def test_traversal_is_forbidden(client):
    """`..` in the served path must not escape UPLOADS_PATH.

    Percent-encoded, on purpose: a literal `../` is collapsed by the router
    before the handler ever sees it, so only `%2e%2e` actually reaches — and
    exercises — the guard.
    """
    # a secret sitting one level above the uploads root
    secret_path = os.path.join(os.path.dirname(config.UPLOADS_PATH), "secret.txt")
    os.makedirs(os.path.dirname(secret_path), exist_ok=True)
    with open(secret_path, "w") as f:
        f.write("top secret")

    response = client.get("/uploads/%2e%2e/secret.txt")
    assert response.status_code == 403
    assert "top secret" not in response.text

"""simple_oauth suite.

Lives in the plugin, so the harness boots core + simple_oauth for every test
here. The login routes are deliberately open — you must reach them before you
are authenticated.
"""


def test_idp_page_is_served(anon_client):
    """The mock IdP page renders and carries the redirect back."""
    response = anon_client.get(
        "/auth/internal-idp", params={"redirect_uri": "http://testserver/cb"}
    )
    assert response.status_code == 200
    assert 'value="http://testserver/cb"' in response.text


def test_idp_page_escapes_the_redirect_uri(anon_client):
    """`redirect_uri` lands in an HTML attribute — it must not be able to escape it.

    Unescaped, `"><script>` closed the value attribute and the input tag,
    injecting script into a page served from the Cat's own origin.
    """
    payload = '"><script>alert(1)</script>'
    response = anon_client.get(
        "/auth/internal-idp", params={"redirect_uri": payload}
    )

    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;" in response.text


def test_failed_login_url_encodes_the_redirect(anon_client):
    """Wrong key bounces back to the form with the redirect intact, not injected."""
    response = anon_client.post(
        "/auth/internal-idp/login",
        data={"api_key": "definitely-wrong", "redirect_uri": "http://testserver/cb"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    location = response.headers["location"]
    assert "http%3A%2F%2Ftestserver%2Fcb" in location
    assert "?redirect_uri=http://" not in location


def test_login_unknown_handler_is_404(anon_client):
    response = anon_client.get("/auth/login/nonexistent", follow_redirects=False)
    assert response.status_code == 404

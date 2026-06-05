from ruckus_dashboard.app import create_app


def test_styles_css_served():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/styles.css")
        assert r.status_code == 200
        assert b"--bg" in r.data  # CSS custom properties present


def test_logo_served():
    app = create_app({"SECRET_KEY": "t"})
    with app.test_client() as c:
        r = c.get("/static/assets/ruckus-logo.png")
        assert r.status_code == 200
        assert r.data.startswith(b"\x89PNG")

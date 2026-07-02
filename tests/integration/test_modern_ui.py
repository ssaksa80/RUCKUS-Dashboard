"""Modern-UI refresh (flag-gated) — slice 1: token layer + Overview.

The refresh is gated behind ``RUCKUS_MODERN_UI`` (default False). With the flag
OFF the app must render byte-for-byte as the legacy UI: ``base.html`` carries
``data-ui="legacy"`` and no ``body[data-ui="modern"]`` skin is active. With the
flag ON the shell opts in via ``data-ui="modern"`` and the modern skin markers
are present in the served ``styles.css``.

Assertion idiom follows ``test_motion_ui.py`` (read the CSS source directly for
token/skin markers) and ``test_pages.py`` (assert the CSP response header + the
rendered ``<body>`` tag).
"""
import pathlib

from ruckus_dashboard.app import create_app

CSS = pathlib.Path("RUCKUS/ruckus_dashboard/static/styles.css")
DASH_JS = pathlib.Path("RUCKUS/ruckus_dashboard/static/dashboard.js")
FONTS_README = pathlib.Path("RUCKUS/ruckus_dashboard/static/fonts/README.md")


def _css():
    return CSS.read_text(encoding="utf-8")


def _authed(flag_on: bool):
    """Return a test client with an authenticated overview session.

    The overview page only renders when RUCKUS_ENABLE_NEW_UI is on and a
    session is authenticated; RUCKUS_MODERN_UI is the independent skin flag.
    """
    app = create_app({
        "SECRET_KEY": "t",
        "RUCKUS_ENABLE_NEW_UI": True,
        "RUCKUS_MODERN_UI": flag_on,
    })
    c = app.test_client()
    c.get("/")
    with c.session_transaction() as s:
        s["auth"] = True
        s["connection_ids"] = []
    return c


# ── Config flag ────────────────────────────────────────────────────────────
def test_modern_ui_flag_defaults_off():
    app = create_app({"SECRET_KEY": "t"})
    assert app.config.get("RUCKUS_MODERN_UI") is False


def test_modern_ui_flag_reads_env(monkeypatch):
    from ruckus_dashboard.config import build_config
    monkeypatch.setenv("RUCKUS_MODERN_UI", "1")
    cfg = build_config(".")
    assert cfg["RUCKUS_MODERN_UI"] is True


# ── base.html shell hook ─────────────────────────────────────────────────────
def test_base_body_is_legacy_when_flag_off():
    c = _authed(flag_on=False)
    body = c.get("/").data.decode()
    assert 'data-ui="legacy"' in body
    assert 'data-ui="modern"' not in body


def test_base_body_is_modern_when_flag_on():
    c = _authed(flag_on=True)
    body = c.get("/").data.decode()
    assert 'data-ui="modern"' in body
    # A default theme is carried so the dark NOC skin is the baseline.
    assert 'data-theme=' in body


def test_module_page_also_carries_modern_flag():
    # The shell hook lives in base.html, so every page (not just overview)
    # opts in when the flag is on.
    app = create_app({
        "SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True, "RUCKUS_MODERN_UI": True,
    })
    with app.test_client() as c:
        body = c.get("/m/aps").data.decode()
        assert 'data-ui="modern"' in body


# ── Token layer + modern skin markers in served CSS ──────────────────────────
def test_root_token_layer_present():
    css = _css()
    for token in [
        "--surface", "--text", "--border",
        "--role-success", "--role-warning", "--role-danger", "--role-accent",
        "--radius", "--space-",
    ]:
        assert token in css, f"missing design token {token}"


def test_reuses_existing_sp5_glow_and_motion_tokens_not_duplicated():
    css = _css()
    # The SP5 tokens must still be defined exactly once (no duplicate :root
    # decl of the same glow token, which would mean we copied instead of reused).
    for token in ["--glow-ok", "--glow-critical", "--motion-base", "--ease-out"]:
        assert css.count(f"{token}:") == 1, f"{token} should be declared once"


def test_modern_skin_is_scoped_under_data_ui_modern():
    css = _css()
    assert 'body[data-ui="modern"]' in css
    # Modern skin surface markers (app shell, KPI/metric cards, status pills,
    # fleet-health bar) must be scoped, so legacy is never touched.
    assert "tabular-nums" in css


def test_modern_desk_theme_variant_present():
    css = _css()
    assert 'body[data-ui="modern"][data-theme="desk"]' in css


def test_modern_uses_system_font_stack_and_font_face_hook():
    css = _css()
    # System-ui stack under modern (CSP-safe, no external fonts).
    assert "system-ui" in css
    # A commented @font-face hook pointing at a self-hosted, same-origin woff2.
    assert "ui.woff2" in css


def test_fonts_readme_documents_self_host_hook():
    txt = FONTS_README.read_text(encoding="utf-8")
    assert "woff2" in txt
    # Must call out that this is same-origin / CSP-safe.
    assert "same-origin" in txt.lower() or "csp" in txt.lower()


# ── Overview modern markers (status ribbon + KPI + fleet health) ─────────────
def test_overview_has_status_ribbon_hook():
    # The status-ribbon element must exist so modern CSS can style it and the
    # existing JS can populate it. It is inert/hidden in legacy.
    c = _authed(flag_on=True)
    body = c.get("/").data.decode()
    assert "data-status-ribbon" in body


def test_overview_ribbon_present_but_inert_in_legacy():
    # Flag OFF: the ribbon element may exist in the DOM but must be hidden so
    # the legacy overview looks exactly as before.
    c = _authed(flag_on=False)
    body = c.get("/").data.decode()
    if "data-status-ribbon" in body:
        # The element ships with a `hidden` attribute; the modern skin reveals
        # it. Assert the `hidden` attribute travels with the ribbon markup so
        # the legacy overview shows nothing new.
        at = body.index("data-status-ribbon")
        assert "hidden" in body[max(0, at - 120):at + 120]


def test_dashboard_js_populates_status_ribbon():
    js = DASH_JS.read_text(encoding="utf-8")
    # The warmup stream (existing tile data flow) also drives the ribbon.
    assert "data-status-ribbon" in js or "status-ribbon" in js


# ── CSP regression guard (no external font/script origin crept in) ───────────
def test_csp_script_src_still_strictly_self_with_modern_flag():
    app = create_app({
        "SECRET_KEY": "t", "RUCKUS_ENABLE_NEW_UI": True, "RUCKUS_MODERN_UI": True,
    })
    with app.test_client() as c:
        csp = c.get("/healthz").headers["Content-Security-Policy"]
        assert "script-src 'self'" in csp
        script_dir = [p.strip() for p in csp.split(";")
                      if p.strip().startswith("script-src")][0]
        # No CDN / external origin snuck into script-src.
        assert "http://" not in script_dir and "https://" not in script_dir
        assert "default-src 'self'" in csp
        # No external font/style origins either (Google Fonts, etc.).
        assert "fonts.googleapis" not in csp and "fonts.gstatic" not in csp


def test_no_external_font_origin_in_css():
    css = _css()
    # Fonts are same-origin (url_for static) or system only — never a CDN.
    assert "fonts.googleapis" not in css
    assert "fonts.gstatic" not in css
    assert "https://" not in css  # no external asset URLs at all


# ── prefers-reduced-motion still a single block ──────────────────────────────
def test_single_reduced_motion_block_survives():
    css = _css()
    assert css.count("@media (prefers-reduced-motion: reduce)") == 1

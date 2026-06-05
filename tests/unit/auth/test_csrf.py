import pytest
from flask import Flask, session
from werkzeug.exceptions import BadRequest
from ruckus_dashboard.auth.csrf import validate_csrf


def make_app():
    app = Flask(__name__)
    app.secret_key = "test"
    return app


def test_valid_token_passes():
    app = make_app()
    with app.test_request_context("/x", method="POST", data={"csrf_token": "abc"}):
        session["csrf_token"] = "abc"
        validate_csrf()  # no raise


def test_missing_token_400():
    app = make_app()
    with app.test_request_context("/x", method="POST"):
        session["csrf_token"] = "abc"
        with pytest.raises(BadRequest):
            validate_csrf()


def test_mismatched_token_400():
    app = make_app()
    with app.test_request_context("/x", method="POST", data={"csrf_token": "wrong"}):
        session["csrf_token"] = "abc"
        with pytest.raises(BadRequest):
            validate_csrf()


def test_header_token_passes():
    app = make_app()
    with app.test_request_context(
        "/x", method="POST", headers={"X-CSRF-Token": "abc"}
    ):
        session["csrf_token"] = "abc"
        validate_csrf()  # no raise

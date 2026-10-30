"""The demo app must be reproducible only by actually driving the form.

Run with: python -m pytest tests/test_demo_server.py -v
"""

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from tests.demo_server import LOGIN_PAGE, app

# The words the generate prompt tells scripts to look for in the visible body text.
TRIGGERS = ("invalid", "incorrect", "error", "failed", "could not", "unable to")


def visible_text(html: str) -> str:
    """Rough equivalent of Selenium's body.text: markup and CSS removed."""
    stripped = re.sub(r'<head>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)
    stripped = re.sub(r'<style>.*?</style>', '', stripped, flags=re.DOTALL | re.IGNORECASE)
    return re.sub(r'<[^>]+>', ' ', stripped).lower()


@pytest.fixture
def client():
    app.config.update(TESTING=True)
    return app.test_client()


def test_the_unsubmitted_page_shows_no_sign_of_the_bug(client):
    """Otherwise any script "reproduces" the bug before touching the form."""
    text = visible_text(client.get("/login").get_data(as_text=True))
    assert [word for word in TRIGGERS if word in text] == []


def test_submitting_the_form_reveals_the_bug(client):
    text = visible_text(
        client.post("/login", data={"username": "u", "password": "p"}).get_data(as_text=True))
    assert "invalid" in text


def test_the_page_template_keeps_its_error_placeholder():
    assert "{error_html}" in LOGIN_PAGE

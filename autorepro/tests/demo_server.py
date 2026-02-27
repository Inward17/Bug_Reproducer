"""Demo server: Flask app simulating a buggy login page for E2E testing."""

from flask import Flask, request

app = Flask(__name__)


@app.route("/login")
def login():
    """Render the login form."""
    return """<html><body>
      <form method="post" action="/login">
        <input id="username" name="username" type="text" placeholder="Username"/>
        <input id="password" name="password" type="password" placeholder="Password"/>
        <button id="submit" type="submit">Login</button>
      </form></body></html>"""


@app.route("/login", methods=["POST"])
def login_post():
    """Always return 'Invalid credentials' — simulates the bug."""
    return '<html><body><div id="error">Invalid credentials</div></body></html>'


if __name__ == "__main__":
    app.run(port=8080)

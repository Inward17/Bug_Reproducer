"""Node 1.5 — DOM inspection: fetch target page and extract interactive elements."""

import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from agent.state import AgentState
from utils.logger import get_logger
from utils.net import BlockedTargetError, check_target

log = get_logger(__name__)

# Tags that represent interactive or important elements
INTERACTIVE_TAGS = ["a", "button", "input", "select", "textarea", "form", "label", "nav", "h1", "h2", "h3"]
MAX_DOM_CHARS = 3000  # Keep DOM context under this limit to fit LLM context window


def _in_container() -> bool:
    """True when this process is itself running inside a container."""
    return Path("/.dockerenv").exists()


def _host_url(url: str) -> str:
    """Translate Docker-internal URLs to an address this process can reach.

    On a developer machine the API runs on the host, where 'host.docker.internal'
    doesn't resolve, so it becomes 'localhost'. Inside a container it resolves via
    extra_hosts, and rewriting it to localhost would point at the API container itself.
    """
    if _in_container():
        return url
    return re.sub(r'host\.docker\.internal', 'localhost', url, flags=re.IGNORECASE)


def _extract_elements(soup: BeautifulSoup) -> str:
    """Extract interactive elements with their attributes into a readable summary."""
    lines = []
    length = 0

    for tag in soup.find_all(INTERACTIVE_TAGS):
        attrs = {}

        # Core identifiers
        if tag.get("id"):
            attrs["id"] = tag["id"]
        if tag.get("class"):
            attrs["class"] = " ".join(tag["class"])
        if tag.get("name"):
            attrs["name"] = tag["name"]
        if tag.get("type"):
            attrs["type"] = tag["type"]
        if tag.get("href"):
            href = tag["href"]
            # Truncate long hrefs
            if len(href) > 80:
                href = href[:77] + "..."
            attrs["href"] = href
        if tag.get("placeholder"):
            attrs["placeholder"] = tag["placeholder"]
        if tag.get("value"):
            attrs["value"] = tag["value"][:50]
        if tag.get("role"):
            attrs["role"] = tag["role"]
        if tag.get("aria-label"):
            attrs["aria-label"] = tag["aria-label"]
        if tag.get("onclick"):
            attrs["onclick"] = tag["onclick"][:80]
        if tag.get("for"):
            attrs["for"] = tag["for"]

        # Get visible text (truncated)
        text = tag.get_text(strip=True)
        if text and len(text) > 60:
            text = text[:57] + "..."

        # Build element summary line
        attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
        if text:
            line = f"<{tag.name} {attr_str}>{text}</{tag.name}>"
        else:
            line = f"<{tag.name} {attr_str} />"

        lines.append(line)
        length += len(line) + 1
        if length > MAX_DOM_CHARS:
            lines.append(f"... (truncated, {len(soup.find_all(INTERACTIVE_TAGS))} total elements)")
            break

    return "\n".join(lines)


def _fetch_dom_via_sandbox(url: str, job_id: str) -> str:
    """Fetch the fully rendered DOM of an SPA by running a Selenium script in the sandbox."""
    import json

    from sandbox import runner
    from storage.artifacts import artifacts_dir

    log.info("inspect_spa_fallback_start", job_id=job_id, url=url)

    # json.dumps gives a safely quoted Python/JSON string literal, so a URL containing
    # a quote or newline can't break out of the generated script.
    script_code = f"""import time
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options

options = Options()
options.add_argument("--headless")
options.add_argument("--no-sandbox")
options.add_argument("--disable-dev-shm-usage")
options.binary_location = "/usr/bin/chromium"
service = Service("/usr/bin/chromedriver")
driver = webdriver.Chrome(service=service, options=options)

try:
    driver.get({json.dumps(url)})
    time.sleep(3)  # Wait for SPA to render
    with open("/screenshots/dom.html", "w", encoding="utf-8") as f:
        f.write(driver.page_source)
finally:
    driver.quit()
"""
    job_artifacts_dir = artifacts_dir(job_id)
    script_path = job_artifacts_dir / "inspect_spa.py"
    script_path.write_text(script_code, encoding="utf-8")

    runner.run(str(script_path), job_id, attempt=0)

    dom_file = job_artifacts_dir / "dom.html"
    if dom_file.exists():
        log.info("inspect_spa_fallback_success", job_id=job_id)
        return dom_file.read_text(encoding="utf-8", errors="replace")

    log.warning("inspect_spa_fallback_missing_output", job_id=job_id)
    return ""


def inspect_node(state: AgentState) -> AgentState:
    """Fetch the target page and extract interactive DOM elements.

    Never raises. A 404/500 page, a login wall or a bot check is often the very symptom
    being reported, so the run continues with whatever context is available and lets the
    sandbox — which has the same network view as the script — be the judge.
    """
    url = state["target_url"]
    job_id = state["job_id"]
    log.info("inspect_start", job_id=job_id, url=url)

    try:
        check_target(url)
    except BlockedTargetError as e:
        log.warning("inspect_blocked", job_id=job_id, error=str(e))
        return {**state, "dom_context": f"(Target refused by the SSRF guard: {e})"}

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    status = None
    html = ""
    try:
        resp = requests.get(_host_url(url), headers=headers, timeout=15)
        raw_status = getattr(resp, "status_code", None)
        status = raw_status if isinstance(raw_status, int) else None
        html = resp.text if isinstance(resp.text, str) else ""
    except Exception as e:
        log.warning("inspect_fetch_failed", job_id=job_id, error=str(e))
        return {**state, "dom_context": (
            f"(Could not fetch the page from the API host: {e}. The target may only be "
            f"reachable from the sandbox network. Infer selectors from the bug report, "
            f"and print the page text so the next attempt can see the real content.)")}

    soup = BeautifulSoup(html, "html.parser")
    elements = _extract_elements(soup)

    # SPA fallback: a page whose markup carries no interactive tags was probably rendered
    # client-side, so re-fetch it through a real browser.
    if not elements.strip():
        log.info("inspect_static_empty", job_id=job_id)
        try:
            rendered_html = _fetch_dom_via_sandbox(url, job_id)
        except Exception as e:
            log.warning("inspect_spa_fallback_failed", job_id=job_id, error=str(e))
            rendered_html = ""
        if rendered_html:
            soup = BeautifulSoup(rendered_html, "html.parser")
            elements = _extract_elements(soup)

    title = soup.title.string.strip() if soup.title and soup.title.string else "Unknown"
    status_note = f"HTTP status: {status}"
    if status is not None and status >= 400:
        status_note += "  <- the error page itself may be the reported bug"

    dom_context = (f"Page Title: {title}\nURL: {url}\n{status_note}\n\n"
                   f"Interactive elements found on the page:\n{elements or '(none found)'}")
    log.info("inspect_success", job_id=job_id, status=status,
             elements_found=len(elements.splitlines()))
    return {**state, "dom_context": dom_context}

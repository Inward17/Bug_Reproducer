"""Node 1.5 — DOM inspection: fetch target page and extract interactive elements."""

import re
import requests
from bs4 import BeautifulSoup

from agent.state import AgentState
from utils.logger import get_logger

log = get_logger(__name__)


def _host_url(url: str) -> str:
    """Translate Docker-internal URLs to host-reachable equivalents.

    The inspect node runs on the host machine (Windows/macOS), where
    'host.docker.internal' doesn't resolve. We swap it to 'localhost'
    so requests.get() can actually reach the target app.
    """
    return re.sub(
        r'host\.docker\.internal',
        'localhost',
        url,
        flags=re.IGNORECASE,
    )

# Tags that represent interactive or important elements
INTERACTIVE_TAGS = ["a", "button", "input", "select", "textarea", "form", "label", "nav", "h1", "h2", "h3"]
MAX_DOM_CHARS = 3000  # Keep DOM context under this limit to fit LLM context window


def _extract_elements(soup: BeautifulSoup) -> str:
    """Extract interactive elements with their attributes into a readable summary."""
    lines = []

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

        # Stop if we're getting too long
        total = "\n".join(lines)
        if len(total) > MAX_DOM_CHARS:
            lines.append(f"... (truncated, {len(soup.find_all(INTERACTIVE_TAGS))} total elements)")
            break

    return "\n".join(lines)


def inspect_node(state: AgentState) -> AgentState:
    """Fetch the target page and extract interactive DOM elements."""
    url = state["target_url"]
    log.info("inspect_start", job_id=state["job_id"], url=url)

    try:
        # Use a browser-like User-Agent to avoid blocks
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        resp = requests.get(_host_url(url), headers=headers, timeout=15, verify=False)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Extract page title
        title = soup.title.string.strip() if soup.title and soup.title.string else "Unknown"

        # Extract interactive elements
        elements = _extract_elements(soup)

        dom_context = f"Page Title: {title}\nURL: {url}\n\nInteractive elements found on the page:\n{elements}"

        log.info("inspect_success", job_id=state["job_id"], elements_found=len(elements.splitlines()))
        return {**state, "dom_context": dom_context}

    except Exception as e:
        log.warning("inspect_failed", job_id=state["job_id"], error=str(e))
        # Non-fatal: if we can't fetch, just continue without DOM context
        dom_context = f"(Could not fetch page DOM: {e}. The LLM must infer selectors from the bug report.)"
        return {**state, "dom_context": dom_context}

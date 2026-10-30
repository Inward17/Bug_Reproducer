"""Mock LLM for testing without API keys. Returns realistic hardcoded responses."""

import json


class MockResponse:
    """Mimics a LangChain AI message response."""

    def __init__(self, content: str):
        self.content = content


class MockLLM:
    """Mock LLM that returns predefined responses based on prompt content."""

    def invoke(self, prompt: str) -> MockResponse:
        """Return a realistic mock response based on the prompt type."""
        if "Analyse the bug report" in prompt or "Analyze the bug report" in prompt:
            return MockResponse(json.dumps({
                "inferred_steps": [
                    "Navigate to the login page",
                    "Enter valid username in the username field",
                    "Enter valid password in the password field",
                    "Click the Login/Submit button",
                    "Observe the error message displayed"
                ],
                "target_elements": [
                    "#username",
                    "#password",
                    "#submit",
                    "#error"
                ],
                "expected_behavior": "User should be logged in and redirected to dashboard after entering correct credentials",
                "success_condition": "The text 'Invalid credentials' appears on screen after submitting valid login credentials, proving the bug is reproduced",
                "bug_variants": [
                    {
                        "interpretation": "The server rejects every login attempt",
                        "success_condition": "Verify the visible body text contains 'Invalid' after submitting valid credentials",
                    },
                    {
                        "interpretation": "The form fails silently and stays on the login page",
                        "success_condition": "Verify the visible body text still contains 'Sign in' after submitting",
                    },
                ],
                "risk_factors": [
                    "Form may use AJAX instead of traditional submit",
                    "Error element may take time to appear",
                    "CSRF tokens might be required"
                ]
            }, indent=2))

        if "previously generated" in prompt or "PREVIOUS SCRIPT" in prompt:
            return MockResponse(
                "The verification condition looked for a successful redirect instead of the "
                "error message.\nFixed by checking the visible body text for 'Invalid'.\n\n"
                "```python\n" + self._script(prompt) + "\n```"
            )

        if "Write a Python script" in prompt or "Selenium automation expert" in prompt:
            return MockResponse(self._script(prompt))

        return MockResponse('{"error": "unknown prompt type"}')

    def _script(self, prompt: str) -> str:
        """Generate a mock Selenium script that follows the verdict contract."""
        import re
        url_match = re.search(r'Target URL:\s*(\S+)', prompt)
        target_url = url_match.group(1) if url_match else "http://host.docker.internal:8080/login"

        return f'''import json
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = None
reproduced = False
variant = ""
evidence = ""
try:
    print("Step 1: Setting up Chrome driver")
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.binary_location = "/usr/bin/chromium"
    service = Service("/usr/bin/chromedriver")
    driver = webdriver.Chrome(service=service, options=options)

    print("Step 2: Navigating to login page")
    driver.get("{target_url}")
    driver.save_screenshot("/screenshots/step_1_page_loaded.png")

    print("Step 3: Filling in valid credentials")
    WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "username"))
    ).send_keys("testuser")
    driver.find_element(By.ID, "password").send_keys("correctpassword123")
    driver.save_screenshot("/screenshots/step_2_form_filled.png")

    print("Step 4: Submitting the form")
    driver.find_element(By.ID, "submit").click()
    time.sleep(2)
    driver.save_screenshot("/screenshots/step_3_after_submit.png")

    print("Step 5: Reading the page")
    visible_text = driver.find_element(By.TAG_NAME, "body").text
    print("PAGE_TEXT:", visible_text[:500])

    for needle in ("invalid", "incorrect"):
        if needle in visible_text.lower():
            reproduced, variant, evidence = True, "variant 1: error text", needle
            break

    driver.save_screenshot("/screenshots/step_4_result.png")
except Exception as e:
    print(f"Error: {{e}}")
    if driver:
        driver.save_screenshot(f"/screenshots/failure_{{int(time.time())}}.png")
    raise
finally:
    print("AUTOREPRO_RESULT " + json.dumps(
        {{"reproduced": reproduced, "variant": variant, "evidence": evidence[:300]}}))
    if driver:
        driver.quit()
'''

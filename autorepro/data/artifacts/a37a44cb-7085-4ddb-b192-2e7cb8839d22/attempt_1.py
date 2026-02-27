import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

driver = None
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
    driver.get("http://host.docker.internal:8080/login")

    print("Step 3: Entering username")
    username_field = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "username"))
    )
    username_field.send_keys("testuser")

    print("Step 4: Entering password")
    password_field = driver.find_element(By.ID, "password")
    password_field.send_keys("correctpassword123")

    print("Step 5: Clicking submit button")
    submit_button = driver.find_element(By.ID, "submit")
    submit_button.click()

    print("Step 6: Checking for error message")
    error_element = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "error"))
    )

    if "Invalid credentials" in error_element.text:
        print("Bug confirmed: Login shows Invalid credentials even with correct credentials")
        print("REPRODUCED")
    else:
        raise AssertionError(f"Expected 'Invalid credentials' but got: {error_element.text}")

except Exception as e:
    print(f"Error: {e}")
    if driver:
        driver.save_screenshot(f"/screenshots/failure_{int(time.time())}.png")
    raise
finally:
    if driver:
        driver.quit()
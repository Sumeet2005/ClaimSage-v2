import os
from datetime import datetime
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


def run_smoke_test():
    email = os.environ.get("CLAIMSAGE_SMOKE_EMAIL")
    password = os.environ.get("CLAIMSAGE_SMOKE_PASSWORD")
    if not email or not password:
        raise RuntimeError("Set CLAIMSAGE_SMOKE_EMAIL and CLAIMSAGE_SMOKE_PASSWORD locally.")

    frontend_url = os.environ.get(
        "CLAIMSAGE_FRONTEND_URL",
        "http://127.0.0.1:5173",
    ).rstrip("/")
    claim_id = os.environ.get(
        "CLAIMSAGE_SMOKE_CLAIM_ID",
        "ba0a770f-e8d5-480f-bd19-fbcd56a45eb4",
    )

    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--window-size=1280,1024")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 15)
    investigation_wait = WebDriverWait(driver, 180)

    def save_screenshot(label):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = Path(__file__).resolve().with_name(f"smoke_test_{label}_{timestamp}.png")
        driver.save_screenshot(str(path))
        print(f"Saved screenshot to {path}")

    try:
        print("STEP 1: Navigate to ClaimSage frontend...")
        driver.get(frontend_url)

        # Verify login page
        print("STEP 2: Testing Login page in browser...")
        email_input = wait.until(EC.presence_of_element_located((By.ID, "email")))
        password_input = driver.find_element(By.ID, "password")
        login_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")

        email_input.send_keys(email)
        password_input.send_keys(password)
        login_btn.click()

        # Wait for claims dashboard
        print("STEP 3: Testing Claims Dashboard...")
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[normalize-space()='Your claims, in context.']")
            )
        )
        print("Dashboard loaded successfully. Current URL:", driver.current_url)

        # Find and click on the synthetic claim
        print("STEP 4: Opening synthetic claim...")
        driver.get(f"{frontend_url}/claims/{claim_id}")

        # Verify claim details loaded
        wait.until(
            EC.presence_of_element_located((By.XPATH, "//*[contains(text(), 'Claim overview')]"))
        )
        print("Claim detail page loaded.")

        # Update policy metadata
        print("STEP 5: Testing Policy Metadata Form update...")
        policy_id_input = wait.until(
            EC.presence_of_element_located((By.ID, "claim-policy-identifier"))
        )
        loss_date_input = driver.find_element(By.ID, "claim-loss-date")
        checkbox = driver.find_element(By.CSS_SELECTOR, "input[type='checkbox']")

        policy_id_input.clear()
        policy_id_input.send_keys("POL-AUTO-2026-X1")

        loss_date_input.clear()
        loss_date_input.send_keys("2026-03-15")

        if not checkbox.is_selected():
            checkbox.click()

        save_btn = driver.find_element(
            By.XPATH, "//button[contains(., 'Save verified policy metadata')]"
        )
        save_btn.click()

        # Wait for success status
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Policy metadata was saved')]")
            )
        )
        print("Policy metadata update succeeded in browser.")

        # Upload evidence
        print("STEP 6: Testing Evidence Upload...")
        file_input = driver.find_element(By.ID, "claim-evidence-file")
        pdf_path = Path(__file__).resolve().with_name("smoke_test_evidence.pdf")
        file_input.send_keys(str(pdf_path))

        upload_btn = wait.until(
            EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Upload PDF')]"))
        )
        upload_btn.click()

        # Wait for processed response
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Evidence upload processed')]")
            )
        )
        print("Evidence upload processed successfully in browser.")

        # Run AI investigation
        print("STEP 7: Testing AI Investigation...")
        task_area = driver.find_element(By.ID, "investigation-task")
        task_area.clear()
        task_area.send_keys(
            "Review the police report evidence and evaluate auto collision coverage."
        )

        investigate_btn = driver.find_element(
            By.XPATH, "//button[contains(., 'Run investigation')]"
        )
        investigate_btn.click()

        print("STEP 8: Verifying human-reviewed report...")
        investigation_wait.until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section[aria-label='Review report']"))
        )
        wait.until(
            EC.presence_of_element_located(
                (By.XPATH, "//*[contains(text(), 'Human review is required')]")
            )
        )
        print("Investigation report loaded and requires human review.")

        save_screenshot("result")
        print("SMOKE TEST COMPLETE: SUCCESS!")

    except Exception as e:
        print("SMOKE TEST ERROR:", type(e).__name__)
        save_screenshot("error")
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    run_smoke_test()

from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # Navigate to the login page
        page.goto("http://127.0.0.1:5001/login")

        # Wait for the password field to be visible before filling it
        password_field = page.get_by_label("Mot de passe")
        expect(password_field).to_be_visible()
        password_field.fill("your_secure_password_here")
        page.get_by_role("button", name="Se connecter").click()

        # Wait for navigation to the main page
        expect(page).to_have_url("http://127.0.0.1:5001/")

        # Click the "Bandes-annonces" button in the sidebar using its ID
        page.locator("#standalone-trailer-search-btn").click()

        # Wait for the standalone search modal to appear
        modal = page.locator("#standalone-trailer-search-modal")
        expect(modal).to_be_visible()

        # Enter a search query and submit
        page.get_by_placeholder("Entrez un titre de film ou de série...").fill("Inception")
        page.locator("#execute-standalone-trailer-search-btn").click()

        # Wait for the results to load
        expect(page.locator("#standalone-trailer-search-results-container .list-group-item")).to_have_count(1, timeout=10000)


        # Take a screenshot of the modal with the results
        modal.screenshot(path="jules-scratch/verification/verification.png")

    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)
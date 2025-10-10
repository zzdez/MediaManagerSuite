import re
from playwright.sync_api import sync_playwright, Page, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Login
        page.goto("http://localhost:5001/login")
        page.get_by_label("Mot de passe").fill("password")
        page.get_by_role("button", name="Se connecter").click()
        expect(page).to_have_url(re.compile(".*localhost:5001/.*"), timeout=10000)

        # 2. Navigate to a page where the global JS is loaded (homepage is fine)
        page.goto("http://localhost:5001/")
        expect(page.get_by_role("heading", name="Portail Media Manager Suite")).to_be_visible()

        # 3. Directly trigger the custom event to open the trailer modal for a TV show
        # This bypasses the need for a valid TMDB/TVDB API key for the initial search
        page.evaluate("""() => {
            $(document).trigger('openTrailerSearch', {
                mediaType: 'tv',
                externalId: '431488',
                title: 'The Last Frontier'
            });
        }""")

        # 4. Take a screenshot of the modal
        trailer_modal = page.locator("#trailer-selection-modal")
        expect(trailer_modal).to_be_visible()

        # 5. Wait for the API call to finish and content to be rendered
        # We expect an error message because the YOUTUBE_API_KEY is fake.
        # This is a good test of the error handling pathway.
        expect(trailer_modal.locator(".spinner-border")).not_to_be_visible(timeout=20000)
        expect(trailer_modal.get_by_text("Titre du média introuvable.")).to_be_visible(timeout=10000)

        trailer_modal.screenshot(path="jules-scratch/verification/verification.png")

    except Exception as e:
        print(f"An error occurred during Playwright verification: {e}")
        page.screenshot(path="jules-scratch/verification/error_screenshot.png")
    finally:
        context.close()
        browser.close()

with sync_playwright() as playwright:
    run(playwright)
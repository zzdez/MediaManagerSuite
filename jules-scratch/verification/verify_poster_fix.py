
import re
from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # Log in
    page.goto("http://127.0.0.1:5001/login")
    page.get_by_label("Mot de passe").fill("your_secure_password_here")
    page.get_by_role("button", name="Se connecter").click()
    expect(page).to_have_url("http://127.0.0.1:5001/")

    # Go to the search page
    page.goto("http://127.0.0.1:5001/search/")

    # Click on "Recherche Libre" tab
    page.get_by_role("tab", name="Recherche Libre").click()

    # Perform a search
    page.get_by_placeholder("Titre du film ou de la série...").fill("Supernatural S01E01")
    page.get_by_role("button", name="Rechercher").click()

    # Wait for search results and click the first "& Mapper" button
    mapper_button = page.locator('.download-and-map-btn').first
    expect(mapper_button).to_be_visible()
    mapper_button.click()

    # Wait for the modal to appear and click "Voir les Détails"
    details_button = page.locator('.enrich-details-btn').first
    expect(details_button).to_be_visible(timeout=10000) # Increased timeout for the lookup
    details_button.click()

    # Wait for the details card to appear
    details_card = page.locator('.card.bg-dark.text-white').first
    expect(details_card).to_be_visible(timeout=10000)

    # Take a screenshot of the details card
    details_card.screenshot(path="jules-scratch/verification/verification.png")

    # Assert that the poster image has a full URL
    poster_image = details_card.get_by_role("img", name="Poster")
    expect(poster_image).to_have_attribute("src", re.compile(r"^https?://"))

    print("Verification script completed successfully.")

    context.close()
    browser.close()

with sync_playwright() as playwright:
    run(playwright)

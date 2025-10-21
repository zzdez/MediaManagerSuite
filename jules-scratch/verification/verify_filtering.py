
import re
import time
from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    # --- NOUVEAU : Capturer les logs de la console ---
    page.on("console", lambda msg: print(f"CONSOLE: {msg.text()}"))

    try:
        print("Navigating to login page...")
        page.goto("http://localhost:5001", timeout=20000)

        # Se connecter
        password_field = page.get_by_label("Mot de passe")
        expect(password_field).to_be_visible(timeout=10000)
        password_field.fill("your_secure_password_here")
        page.get_by_role("button", name="Se connecter").click()

        expect(page.get_by_role("heading", name="Portail Media Manager Suite")).to_be_visible(timeout=10000)
        print("Login successful, portal page visible.")

        # Naviguer vers l'éditeur Plex
        print("Navigating to Plex Editor page...")
        page.locator('a.portal-link[href="/plex/"]').click()
        expect(page).to_have_url("http://localhost:5001/plex/", timeout=10000)
        print("Plex Editor page loaded.")

        # --- NOUVEAU : Pause pour débogage ---
        print("Pausing for inspection...")
        page.pause()

        print("Selecting user directly with long timeout...")
        user_select = page.locator("#user-select")
        user_select.select_option(index=1, timeout=30000)
        print("User selected.")

        # Attendre le chargement des autres sélecteurs
        library_select = page.locator("#library-select")
        root_folder_select = page.locator("#root-folder-select-main")

        expect(library_select).to_be_enabled(timeout=15000)
        expect(root_folder_select).to_be_enabled(timeout=15000)
        print("Libraries and root folders are enabled.")

        # Appliquer les filtres
        library_select.select_option(label="Séries TV")
        root_folder_select.select_option(label="D:\\Series")
        print("Filters selected.")
        page.get_by_role("button", name="Appliquer les filtres").click()

        # Attendre les résultats
        expect(page.locator("#plex-items-loader")).to_be_hidden(timeout=20000)
        expect(page.locator("#plex-results-table")).to_be_visible(timeout=10000)
        print("Results loaded.")

        page.screenshot(path="jules-scratch/verification/verification.png")
        print("Verification script completed successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
        try:
            print("------ Page Content on Error ------")
            print(page.content())
            print("-----------------------------------")
        except Exception as pe:
            print(f"Could not get page content: {pe}")
        raise e

    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)

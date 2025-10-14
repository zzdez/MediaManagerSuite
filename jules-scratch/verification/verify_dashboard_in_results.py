# jules-scratch/verification/verify_dashboard_in_results.py
from playwright.sync_api import sync_playwright, Page, expect

def verify_dashboard_in_results():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            page.goto("http://127.0.0.1:5001/", timeout=15000)

            # Connexion
            page.get_by_label("Mot de passe").fill("your_secure_password_here")
            page.get_by_role("button", name="Se connecter").click()
            expect(page.get_by_role("heading", name="Tableau de bord Plex")).to_be_visible(timeout=10000)

            # Ouvrir la modale de recherche
            page.get_by_role("button", name="Bandes-annonces").click()
            search_modal = page.locator("#standalone-trailer-search-modal")
            expect(search_modal).to_be_visible()

            # Lancer la recherche
            search_modal.get_by_label("Titre du média").fill("Inception")
            search_modal.get_by_role("button", name="Rechercher").click()

            # Attendre l'apparition du tableau de bord dans le premier résultat
            first_result_dashboard = search_modal.locator(".dashboard-container").first
            expect(first_result_dashboard).to_be_visible()
            expect(first_result_dashboard.get_by_text("Statut:")).to_be_visible(timeout=15000)

            # Prendre la capture d'écran de la modale de recherche
            search_modal.screenshot(path="jules-scratch/verification/dashboard_in_results.png")
            print("Screenshot saved to jules-scratch/verification/dashboard_in_results.png")

        except Exception as e:
            print(f"An error occurred: {e}")
            page.screenshot(path="jules-scratch/verification/error.png")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_dashboard_in_results()

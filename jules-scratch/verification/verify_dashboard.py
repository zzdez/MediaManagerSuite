# jules-scratch/verification/verify_dashboard.py
from playwright.sync_api import sync_playwright, Page, expect

def verify_media_dashboard():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        try:
            # 1. Naviguer vers la page principale
            page.goto("http://127.0.0.1:5001/", timeout=15000)

            # Se connecter
            page.get_by_label("Mot de passe").fill("your_secure_password_here")
            page.get_by_role("button", name="Se connecter").click()
            expect(page.get_by_role("heading", name="Tableau de bord Plex")).to_be_visible()

            # 2. Ouvrir la modale de recherche de bandes-annonces
            page.get_by_role("button", name="Bandes-annonces").click()
            standalone_modal = page.locator("#standalone-trailer-search-modal")
            expect(standalone_modal).to_be_visible()

            # 3. Effectuer une recherche
            standalone_modal.get_by_label("Titre du média").fill("Inception")
            standalone_modal.get_by_role("button", name="Rechercher").click()

            # 4. Cliquer sur le bouton pour voir les bandes-annonces du premier résultat
            first_result_trailer_button = standalone_modal.get_by_role("button", name="Voir les bandes-annonces").first
            expect(first_result_trailer_button).to_be_visible(timeout=10000)
            first_result_trailer_button.click()

            # 5. Attendre l'apparition de la modale de sélection et du tableau de bord
            selection_modal = page.locator("#trailer-selection-modal")
            expect(selection_modal).to_be_visible()

            dashboard_placeholder = selection_modal.locator("#media-details-placeholder")
            expect(dashboard_placeholder).to_be_visible()

            # Attendre que le contenu soit chargé (vérifier la présence d'un élément spécifique)
            expect(dashboard_placeholder.get_by_text("Statut:")).to_be_visible(timeout=10000)

            # 6. Prendre une capture d'écran de la modale
            selection_modal.screenshot(path="jules-scratch/verification/dashboard_verification.png")
            print("Screenshot saved to jules-scratch/verification/dashboard_verification.png")

        except Exception as e:
            print(f"An error occurred: {e}")
            page.screenshot(path="jules-scratch/verification/error.png")
        finally:
            browser.close()

if __name__ == "__main__":
    verify_media_dashboard()

# jules-scratch/verification/verify_filter_logic.py
import re
from playwright.sync_api import sync_playwright, expect

def run(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # 1. Se connecter
        page.goto("http://localhost:5001/login")
        page.get_by_label("Mot de passe").fill("your_secure_password_here")
        page.get_by_role("button", name="Se connecter").click()

        # Attendre que la page d'accueil soit chargée en vérifiant un élément stable
        expect(page.get_by_role("heading", name="Bienvenue")).to_be_visible(timeout=10000)

        # 2. Naviguer vers l'éditeur Plex
        page.get_by_role("link", name="Plex Editor").click()
        expect(page).to_have_url("http://localhost:5001/plex")

        # 3. Sélectionner un utilisateur (le premier de la liste)
        user_select = page.locator('#user-select')
        user_select.click()
        # Attendre que les options apparaissent et cliquer sur la première
        first_option = page.locator('.select2-results__option').first
        first_option.wait_for(state='visible')
        first_option.click()

        # Attendre que le chargement des bibliothèques soit terminé
        expect(page.locator('#library-select-container .spinner-border')).to_be_hidden(timeout=20000)

        # 4. Sélectionner les bibliothèques
        library_select = page.locator('#library-select')
        library_select.click()
        # Cliquer sur les options contenant 'Films' et 'Séries' (à adapter si les noms sont différents)
        page.get_by_role("treeitem", name="Films").click()
        page.get_by_role("treeitem", name="Séries").click()
        # Fermer la liste déroulante
        library_select.click()

        # Attendre le chargement des dossiers racines
        expect(page.locator('#root-folder-select-container .spinner-border')).to_be_hidden(timeout=20000)

        # 5. Sélectionner les dossiers racines
        root_folder_select = page.locator('#root-folder-select')
        root_folder_select.click()
        # Cliquer sur un dossier Radarr (D:\Films) et un dossier Sonarr (D:\Series)
        page.get_by_role("treeitem", name=re.compile(r"D:\\Films.*")).click()
        page.get_by_role("treeitem", name=re.compile(r"D:\\Series.*")).click()
        # Fermer la liste déroulante
        root_folder_select.click()

        # 6. Lancer la recherche
        page.get_by_role("button", name="Appliquer les filtres").click()

        # Attendre que la table de résultats se mette à jour
        expect(page.locator('#media-table-body .htmx-indicator')).to_be_hidden(timeout=30000)

        # Attendre un court instant pour s'assurer que le rendu est stable
        page.wait_for_timeout(1000)

        # 7. Prendre la capture d'écran
        page.screenshot(path="jules-scratch/verification/verification.png")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error.png")
    finally:
        browser.close()

with sync_playwright() as playwright:
    run(playwright)

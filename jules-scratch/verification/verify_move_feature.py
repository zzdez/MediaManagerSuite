import re
import json
from playwright.sync_api import sync_playwright, expect

def run_verification(playwright):
    browser = playwright.chromium.launch(headless=True)
    context = browser.new_context()
    page = context.new_page()

    try:
        # Mock API calls before navigation
        def handle_media_items(route):
            print(f"Intercepted {route.request.url} to provide mock media items.")
            mock_html = '''
            <tr data-rating-key="12345" data-media-type="sonarr" data-title="My Fake Series">
                <td>My Fake Series</td><td>2023</td><td>-</td><td>-</td><td>-</td><td>-</td>
                <td>
                    <div class="btn-group">
                         <button class="btn btn-sm btn-outline-secondary btn-move" data-bs-toggle="modal" data-bs-target="#move-modal" data-media-id="12345" data-media-type="sonarr" title="Déplacer le média">
                            <i class="bi bi-folder-symlink"></i>
                            <span class="d-none d-lg-inline">Déplacer</span>
                            <span class="spinner-border spinner-border-sm move-in-progress-spinner" role="status" aria-hidden="true" style="display: none;"></span>
                        </button>
                    </div>
                </td>
            </tr>
            '''
            route.fulfill(status=200, content_type="text/html; charset=utf-8", body=mock_html)

        def handle_root_folders(route):
            print(f"Intercepted {route.request.url} to provide mock root folders.")
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps([{'id': '/data/series_new/', 'text': '/data/series_new/'}])
            )

        def handle_move_command(route):
            print(f"Intercepted {route.request.url} to mock move initiation.")
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({'status': 'success', 'message': 'Déplacement initié.', 'task_id': '123-abc'})
            )

        page.route("**/api/media_items", handle_media_items, times=1)
        page.route("**/api/media/root_folders**", handle_root_folders, times=1)
        page.route("**/api/media/move", handle_move_command, times=1)

        # 1. Connexion
        page.goto("http://localhost:5001/login")
        page.get_by_label("Mot de passe").fill("your_secure_password_here")
        page.get_by_role("button", name="Se connecter").click()

        # 2. Attendre la redirection vers la page d'accueil
        expect(page).to_have_url("http://localhost:5001/", timeout=15000)

        # 3. Naviguer manuellement vers l'éditeur Plex
        page.goto("http://localhost:5001/plex")

        # 4. Sélectionner l'utilisateur et la bibliothèque
        expect(page.locator("#user-select-container")).to_be_visible(timeout=15000)
        page.locator("#user-select-container .select2-selection").click()
        page.locator(".select2-results__option", has_text="Principal").click()

        expect(page.locator("#library-select-container")).to_be_visible(timeout=10000)
        page.locator("#library-select-container .select2-selection").click()
        page.locator(".select2-results__option", has_text="Séries").click()

        page.get_by_role("button", name="Afficher").click()
        expect(page.locator("#media-table-body tr")).to_be_visible()

        # 5. Cliquer sur le bouton "Déplacer"
        first_row = page.locator("#media-table-body tr").first
        move_button = first_row.get_by_role("button", name="Déplacer")
        expect(move_button).to_be_enabled()
        move_button.click()

        # 6. Interagir avec la modale
        expect(page.locator("#move-modal")).to_be_visible()
        page.locator("#new-path-select-container .select2-selection").click()
        expect(page.locator(".select2-results__option", has_text="/data/series_new/")).to_be_visible()
        page.locator(".select2-results__option", has_text="/data/series_new/").click()

        page.locator("#confirm-move-btn").click()

        # 7. Vérifier l'état de chargement et prendre la capture d'écran
        expect(first_row.locator(".move-in-progress-spinner")).to_be_visible(timeout=10000)
        expect(first_row).to_have_class(re.compile(r".*row-in-progress.*"))

        first_row.screenshot(path="jules-scratch/verification/verification.png")
        print("Verification script completed successfully.")

    except Exception as e:
        print(f"An error occurred: {e}")
        page.screenshot(path="jules-scratch/verification/error_screenshot.png")
    finally:
        browser.close()

with sync_playwright() as p:
    run_verification(p)
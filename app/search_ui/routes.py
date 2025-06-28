from flask import render_template, request, flash, redirect, url_for # Ajout de redirect et url_for
from . import search_ui_bp
from app.utils.prowlarr_client import search_prowlarr
# Utiliser le login_required défini dans app/__init__.py pour la cohérence
from app import login_required

@search_ui_bp.route('/')
@login_required
def search_page():
    """Affiche la page de recherche initiale."""
    return render_template('search_ui/search.html', title="Recherche")

@search_ui_bp.route('/results')
@login_required
def search_results():
    """Exécute la recherche et affiche les résultats."""
    query = request.args.get('query', '').strip()
    if not query:
        flash("Veuillez entrer un terme à rechercher.", "warning")
        # Rediriger vers la page de recherche si la requête est vide pour éviter d'afficher "Résultats pour """
        return redirect(url_for('search_ui.search_page'))

    results = search_prowlarr(query)

    if results is None:
        flash("Erreur lors de la communication avec Prowlarr. Vérifiez la configuration et les logs de l'application.", "danger")
        results = [] # Initialiser à une liste vide pour que le template ne plante pas

    return render_template('search_ui/search.html', title=f"Résultats pour \"{query}\"", results=results, query=query)

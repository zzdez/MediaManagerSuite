from flask import render_template, request, flash, redirect, url_for # Ajout de redirect et url_for
from . import search_ui_bp
from app.utils.prowlarr_client import search_prowlarr
from app.utils.media_status_checker import check_media_status # Ajout de l'import
# Utiliser le login_required défini dans app/__init__.py pour la cohérence
from app import login_required

@search_ui_bp.route('/')
@login_required
def search_page():
    """Affiche la page de recherche initiale."""
    query = request.args.get('query', '').strip() # Récupérer la query ici aussi
    results = [] # Initialiser results à une liste vide

    if query:
        raw_results = search_prowlarr(query)

        if raw_results is None:
            flash("Erreur de communication avec Prowlarr.", "danger")
            # results reste une liste vide
        elif not raw_results:
            # results reste une liste vide, pas besoin de message spécifique si Prowlarr répond mais n'a pas de résultats
            pass
        else:
            # Enrichir chaque résultat avec les informations de statut
            for result in raw_results:
                result['status_info'] = check_media_status(result['title'])
            results = raw_results

    # Le titre de la page est conditionnel à la présence d'une requête
    page_title = f"Résultats pour \"{query}\"" if query else "Recherche"

    return render_template('search_ui/search.html', title=page_title, results=results, query=query)


# Note: La route /results n'est plus explicitement nécessaire si /search gère tout.
# Si vous souhaitez la conserver pour une raison spécifique (ex: liens directs vers les résultats),
# assurez-vous que sa logique est cohérente avec celle de search_page ou qu'elle redirige.
# Pour l'instant, je vais la commenter pour éviter la duplication de logique.
# Si vous voulez la garder, il faudra la mettre à jour également.

# @search_ui_bp.route('/results')
# @login_required
# def search_results():
#     """Exécute la recherche et affiche les résultats."""
#     query = request.args.get('query', '').strip()
#     if not query:
#         flash("Veuillez entrer un terme à rechercher.", "warning")
#         return redirect(url_for('search_ui.search_page'))

#     raw_results = search_prowlarr(query)

#     if raw_results is None:
#         flash("Erreur de communication avec Prowlarr.", "danger")
#         results = []
#     elif not raw_results:
#         results = []
#     else:
#         # Enrichir chaque résultat avec les informations de statut
#         for result in raw_results:
#             result['status_info'] = check_media_status(result['title'])
#         results = raw_results

#     return render_template('search_ui/search.html', title=f"Résultats pour \"{query}\"", results=results, query=query)

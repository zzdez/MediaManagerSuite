from flask import render_template, request, flash, redirect, url_for, current_app # Ajout de redirect et url_for ET current_app
from . import search_ui_bp
from app.utils.prowlarr_client import search_prowlarr
from app.utils.media_status_checker import check_media_status # Ajout de l'import
from app.utils.plex_client import get_user_specific_plex_server # MOVED IMPORT HERE
# Utiliser le login_required défini dans app/__init__.py pour la cohérence
from app import login_required

@search_ui_bp.route('/')
@login_required
def search_page():
    current_app.logger.warning("<<<<< ENTRÉE DANS search_page >>>>>")
    """Affiche la page de recherche initiale."""
    query = request.args.get('query', '').strip() # Récupérer la query ici aussi
    results = [] # Initialiser results à une liste vide

    if query:
        # --- ÉTAPE 1 : PRÉ-CHARGEMENT DES DONNÉES PLEX ---
        plex_show_cache = {}  # {tvdb_id: plex_show_object}
        plex_episode_cache = {} # {tvdb_id: set((saison, episode))}

        user_plex = get_user_specific_plex_server()
        if user_plex:
            show_libraries = [lib for lib in user_plex.library.sections() if lib.type == 'show']
            for lib in show_libraries:
                current_app.logger.info(f"Pré-chargement des séries et épisodes de '{lib.title}'...")
                # Using lib.all() to fetch all shows, then show.episodes() for each.
                # This is the part that can be slow if a library has many shows,
                # and each show.episodes() call fetches detailed episode info.
                for show in lib.all(): # This fetches all shows in the library
                    tvdb_id_val = None # Initialize tvdb_id_val for each show
                    for guid_obj in show.guids:
                        if 'tvdb' in guid_obj.id:
                            try:
                                tvdb_id_val = int(guid_obj.id.split('//')[1])
                                break # Found TVDB ID, no need to check other GUIDs for this show
                            except (IndexError, ValueError) as e_parse:
                                current_app.logger.warning(f"Could not parse TVDB ID from guid '{guid_obj.id}' for show '{show.title}': {e_parse}")
                                continue # Try next guid if current one is malformed

                    if tvdb_id_val:
                        plex_show_cache[tvdb_id_val] = show
                        # On peuple le cache des épisodes pour cette série
                        # This show.episodes() call is the one that can be very expensive.
                        # It fetches all episode objects for the show.
                        try:
                            plex_episode_cache[tvdb_id_val] = {(e.seasonNumber, e.index) for e in show.episodes()}
                        except Exception as e_episodes:
                            current_app.logger.error(f"Error fetching episodes for show '{show.title}' (TVDB ID: {tvdb_id_val}): {e_episodes}", exc_info=True)
                            plex_episode_cache[tvdb_id_val] = set() # Initialize with empty set on error
                    # else:
                        # current_app.logger.debug(f"No valid TVDB ID found for show '{show.title}' in library '{lib.title}'. Skipping episode caching for this show.")

        current_app.logger.info(f"Cache Plex créé: {len(plex_show_cache)} séries, contenant {sum(len(v) for v in plex_episode_cache.values())} épisodes.")
        # (On fera la même chose pour les films plus tard)

        # --- ÉTAPE 2 : TRAITEMENT DES RÉSULTATS PROWLARR ---
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
                # On passe les deux caches à la fonction de vérification
                result['status_info'] = check_media_status(result['title'], plex_show_cache, plex_episode_cache)
            results = raw_results

    # Le titre de la page est conditionnel à la présence d'une requête
    page_title = f"Résultats pour \"{query}\"" if query else "Recherche"

    current_app.logger.warning("<<<<< SORTIE DE search_page, RENDU DU TEMPLATE >>>>>")
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

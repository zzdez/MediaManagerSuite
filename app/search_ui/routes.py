from flask import render_template, request, flash, redirect, url_for, current_app, jsonify # Ajout de redirect et url_for ET current_app ET jsonify
from . import search_ui_bp
from app.utils.prowlarr_client import search_prowlarr
from app.utils.arr_client import search_sonarr_by_title, search_radarr_by_title
from app.utils.media_status_checker import check_media_status # Ajout de l'import
from app.utils.plex_client import get_user_specific_plex_server # MOVED IMPORT HERE
# Utiliser le login_required défini dans app/__init__.py pour la cohérence
from app import login_required

@search_ui_bp.route('/', methods=['GET'])
@login_required
def search_page():
    query = request.args.get('query', '').strip()
    results = None
    
    if query:
        # --- PRÉ-CHARGEMENT COMPLET PLEX ---
        plex_show_cache, plex_episode_cache, plex_movie_cache = {}, {}, {}
        user_plex = get_user_specific_plex_server()
        if user_plex:
            all_libs = user_plex.library.sections()
            for lib in all_libs:
                if lib.type == 'show':
                    for show in lib.all():
                        tvdb_id = next((int(g.id.split('//')[1]) for g in show.guids if 'tvdb' in g.id), None)
                        if tvdb_id:
                            plex_show_cache[tvdb_id] = show
                            plex_episode_cache[tvdb_id] = {(e.seasonNumber, e.index) for e in show.episodes()}
                elif lib.type == 'movie':
                    for movie in lib.all():
                        tmdb_id = next((int(g.id.split('//')[1]) for g in movie.guids if 'tmdb' in g.id), None)
                        if tmdb_id:
                            plex_movie_cache[tmdb_id] = {'title': movie.title, 'year': movie.year}

        current_app.logger.info(f"Cache Plex créé: {len(plex_show_cache)} séries, {len(plex_movie_cache)} films.")

        # --- TRAITEMENT DES RÉSULTATS PROWLARR ---
        raw_results = search_prowlarr(query)
        if raw_results is not None:
            for result in raw_results:
                result['status_info'] = check_media_status(result['title'], plex_show_cache, plex_episode_cache, plex_movie_cache)
            results = raw_results
        else:
            flash("Erreur de communication avec Prowlarr.", "danger")
            results = []

    return render_template('search_ui/search.html', title="Recherche", results=results, query=query)


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

from flask import jsonify # Ajouté pour la nouvelle route
# Correction de l'import: rTorrentClient n'existe pas, utiliser les fonctions directement
from app.utils.rtorrent_client import add_magnet, get_torrent_hash_by_name
# Correction de l'import: MappingManager n'existe pas comme classe, utiliser les fonctions directement
from app.utils.mapping_manager import add_or_update_torrent_in_map

@search_ui_bp.route('/download-and-map', methods=['POST'])
@login_required
def download_and_map():
    data = request.get_json()
    release_name = data.get('releaseName')
    download_link = data.get('downloadLink')
    instance_type = data.get('instanceType') # 'sonarr' ou 'radarr'
    media_id = data.get('mediaId')

    if not all([release_name, download_link, instance_type, media_id]):
        return jsonify({'status': 'error', 'message': 'Données manquantes.'}), 400

    try:
        # 1. Ajouter le torrent à rTorrent
        # Utiliser add_magnet directement. Supposons que download_link est un lien magnet.
        # La fonction add_magnet retourne (True/False, message)
        # Pour obtenir le hash, nous devrons appeler get_torrent_hash_by_name APRÈS l'ajout.
        # Le label pourrait être 'sonarr' ou 'radarr' en fonction de instance_type pour un suivi.
        label_for_rtorrent = f"mms-{instance_type}-{media_id}" # Exemple de label: mms-sonarr-123

        success, message = add_magnet(download_link, label=label_for_rtorrent)

        if not success:
            return jsonify({'status': 'error', 'message': message or 'Erreur inconnue avec rTorrent lors de l\'ajout du magnet.'}), 500

        # Essayer de récupérer le hash du torrent. Cela peut prendre quelques secondes.
        # Le nom de la release est utilisé pour la recherche du hash.
        torrent_hash = get_torrent_hash_by_name(release_name)

        if not torrent_hash:
             # Si on ne peut pas obtenir le hash, on ne peut pas mapper. C'est un succès partiel.
             flash(f"'{release_name}' ajouté à rTorrent (label: {label_for_rtorrent}), mais le pré-mapping a échoué (hash non récupéré après ajout). Veuillez vérifier manuellement dans rTorrent et mapper si nécessaire.", "warning")
             return jsonify({'status': 'success', 'message': 'Ajouté mais non mappé.'})

        # 2. Sauvegarder le mapping
        # Utiliser add_or_update_torrent_in_map directement.
        # Définir les arguments nécessaires pour add_or_update_torrent_in_map:
        map_label = f"mms-search-{instance_type}-{media_id}"
        # Pour seedbox_download_path, nous supposons un chemin par défaut combiné avec release_name.
        # Idéalement, rTorrent devrait nous dire où il le met, ou cela devrait être configurable.
        # Exemple: /downloads/torrents/mms-sonarr-123/Release Name
        # Pour l'instant, utilisons une convention simple.
        # Si RUTORRENT_DOWNLOAD_DIR est configuré, utilisons-le comme base.
        base_download_dir = current_app.config.get('RUTORRENT_DOWNLOAD_DIR', '/downloads/torrents') # Valeur par défaut si non configuré
        seedbox_dl_path = f"{base_download_dir.rstrip('/')}/{label_for_rtorrent}/{release_name}"

        original_torrent_name = release_name # Au mieux, c'est ce que nous avons

        map_success = add_or_update_torrent_in_map(
            torrent_hash=torrent_hash,
            release_name=release_name,
            app_type=instance_type,
            target_id=str(media_id), # Assurer que c'est une chaîne si la fonction l'attend ainsi
            label=map_label,
            seedbox_download_path=seedbox_dl_path,
            original_torrent_name=original_torrent_name
            # initial_status est par défaut "pending_download_on_seedbox"
        )

        if not map_success:
            flash(f"'{release_name}' ajouté à rTorrent, mais l'écriture du mapping a échoué. Veuillez vérifier les logs.", "danger")
            return jsonify({'status': 'error', 'message': 'Ajouté à rTorrent, mais échec du mapping.'}), 500

        flash(f"'{release_name}' ajouté à rTorrent (label: {label_for_rtorrent}) et pré-associé (hash: {torrent_hash[:8]}...) avec succès !", "success")
        return jsonify({'status': 'success', 'message': 'Téléchargement lancé et mappé.'})

    except Exception as e:
        current_app.logger.error(f"Erreur dans download-and-map: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'Erreur interne du serveur.'}), 500

@search_ui_bp.route('/api/search-arr', methods=['GET'])
def search_arr_proxy():
    query = request.args.get('query')
    media_type = request.args.get('type') # 'sonarr' ou 'radarr'

    if not query:
        return jsonify({'error': 'Le terme de recherche est manquant'}), 400

    results = []
    try:
        if media_type == 'sonarr':
            results = search_sonarr_by_title(query)
        elif media_type == 'radarr':
            results = search_radarr_by_title(query)
        else:
            return jsonify({'error': 'Type de média invalide'}), 400
    except Exception as e:
        current_app.logger.error(f"Erreur lors de la recherche {media_type} pour '{query}': {e}")
        return jsonify({'error': f'Erreur de communication avec {media_type.capitalize()}'}), 500

    return jsonify(results)

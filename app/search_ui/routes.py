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
    release_name = data.get('releaseName') # Correspond à 'releaseName' du JS
    download_link = data.get('downloadLink') # Correspond à 'downloadLink' du JS
    instance_type = data.get('instanceType') # Correspond à 'instanceType' du JS ('sonarr' ou 'radarr')
    media_id = data.get('mediaId') # Correspond à 'mediaId' du JS

    if not all([release_name, download_link, instance_type, media_id]):
        return jsonify({'status': 'error', 'message': 'Données manquantes dans la requête.'}), 400

    try:
        # 1. Ajouter le torrent à rTorrent
        label_for_rtorrent = f"mms-{instance_type}-{media_id}"
        current_app.logger.info(f"Tentative d'ajout du torrent '{release_name}' via le lien '{download_link}' avec le label rTorrent '{label_for_rtorrent}'.")

        success, rtorrent_message = add_magnet(download_link, label=label_for_rtorrent)

        if not success:
            current_app.logger.error(f"Échec de l'ajout du magnet à rTorrent pour '{release_name}'. Message: {rtorrent_message}")
            # Utiliser le message de rtorrent_client s'il existe, sinon un message générique
            error_msg = rtorrent_message or "Erreur inconnue avec rTorrent lors de l'ajout du magnet."
            return jsonify({'status': 'error', 'message': error_msg}), 500

        current_app.logger.info(f"Magnet pour '{release_name}' ajouté avec succès à rTorrent (label: {label_for_rtorrent}). Récupération du hash...")

        # Essayer de récupérer le hash du torrent.
        torrent_hash = get_torrent_hash_by_name(release_name)

        if not torrent_hash:
            # Si on ne peut pas obtenir le hash immédiatement, ce n'est pas nécessairement une erreur fatale pour l'ajout,
            # mais le mapping ne pourra pas se faire. Le message doit être clair.
            current_app.logger.warning(f"Torrent '{release_name}' ajouté à rTorrent, mais le hash n'a pas pu être récupéré immédiatement. Le mapping automatique ne sera pas effectué.")
            # Le message au client doit refléter que l'ajout a eu lieu mais le mapping a échoué.
            # C'est un succès partiel du point de vue de l'utilisateur qui voulait mapper.
            # Cependant, pour la réponse AJAX, il est plus simple de traiter cela comme une erreur de l'opération "download-and-map".
            return jsonify({'status': 'error', 'message': f"Torrent '{release_name}' ajouté, mais le hash n'a pas pu être trouvé pour le mapping. Vérifiez rTorrent."}), 500


        current_app.logger.info(f"Hash '{torrent_hash}' trouvé pour '{release_name}'. Tentative de mapping.")
        # 2. Sauvegarder le mapping
        map_label = f"mms-search-{instance_type}-{media_id}"
        base_download_dir = current_app.config.get('RUTORRENT_DOWNLOAD_DIR', '/downloads/torrents')
        # Le chemin de téléchargement sur le seedbox est souvent <base_dir>/<label_rtorrent>/<nom_release>
        # ou <base_dir>/<nom_release> si rTorrent n'est pas configuré pour créer des sous-dossiers par label.
        # Pour la cohérence avec le comportement précédent où le label était utilisé dans le path:
        seedbox_dl_path = f"{base_download_dir.rstrip('/')}/{label_for_rtorrent}/{release_name}"
        # original_torrent_name est le nom du fichier .torrent original, ici on utilise release_name comme fallback.
        original_torrent_name_for_map = release_name

        map_success = add_or_update_torrent_in_map(
            torrent_hash=torrent_hash,
            release_name=release_name, # Nom de la release (dossier/fichier principal)
            app_type=instance_type,
            target_id=str(media_id), # Assurer que c'est une chaîne
            label=map_label, # Label spécifique au mapping MMS
            seedbox_download_path=seedbox_dl_path, # Chemin complet sur le seedbox
            original_torrent_name=original_torrent_name_for_map
            # initial_status est géré par défaut par add_or_update_torrent_in_map
        )

        if not map_success:
            current_app.logger.error(f"Torrent '{release_name}' (hash: {torrent_hash}) ajouté à rTorrent, mais l'écriture du mapping a échoué.")
            return jsonify({'status': 'error', 'message': f"Torrent '{release_name}' ajouté, mais le mapping a échoué. Vérifiez les logs."}), 500

        final_message = f"Téléchargement pour '{release_name}' (hash: {torrent_hash[:8]}...) lancé et mappé avec succès !"
        current_app.logger.info(final_message)
        return jsonify({'status': 'success', 'message': final_message})

    except Exception as e:
        current_app.logger.error(f"Erreur majeure dans download_and_map pour '{release_name}': {e}", exc_info=True)
        # Renvoyer un message d'erreur générique mais informatif
        return jsonify({'status': 'error', 'message': f"Erreur serveur lors du traitement de '{release_name}': {str(e)}"}), 500

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

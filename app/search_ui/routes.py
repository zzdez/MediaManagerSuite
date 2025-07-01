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

import requests
import json # Added json import
from flask import jsonify
from app.utils.rtorrent_client import add_torrent_data_and_get_hash_robustly, add_magnet_and_get_hash_robustly
from app.utils.mapping_manager import add_or_update_torrent_in_map

@search_ui_bp.route('/download-and-map', methods=['POST'])
@login_required
def download_and_map():
    data = request.get_json()
    release_name = data.get('releaseName')
    download_link = data.get('downloadLink') # Peut être une URL HTTP/S ou un lien magnet:
    instance_type = data.get('instanceType')
    media_id = data.get('mediaId')

    if not all([release_name, download_link, instance_type, media_id]):
        return jsonify({'status': 'error', 'message': 'Données manquantes dans la requête.'}), 400

    torrent_hash = None
    error_msg_add = None
    label_for_rtorrent = f"mms-{instance_type}-{media_id}"

    # Déterminer le chemin de destination en fonction de instance_type
    target_download_path = None
    if instance_type == 'sonarr':
        target_download_path = current_app.config.get('SEEDBOX_SONARR_FINISHED_PATH')
    elif instance_type == 'radarr':
        target_download_path = current_app.config.get('SEEDBOX_RADARR_FINISHED_PATH')

    if not target_download_path:
        current_app.logger.warning(f"Aucun chemin de destination configuré pour instanceType '{instance_type}'. Le torrent sera téléchargé dans le répertoire par défaut de rTorrent.")
        # Optionnel: Renvoyer une erreur ou juste logger et continuer avec le défaut rTorrent
        # return jsonify({'status': 'error', 'message': f"Configuration manquante pour le chemin de destination de {instance_type}."}), 500


    try:
        if download_link.startswith("magnet:"):
            current_app.logger.info(f"Traitement direct du lien magnet pour '{release_name}': {download_link}")
            torrent_hash, error_msg_add = add_magnet_and_get_hash_robustly(
                download_link,
                label=label_for_rtorrent,
                destination_path=target_download_path
            )
        else: # Supposé être une URL HTTP/S
            current_app.logger.info(f"Traitement de l'URL HTTP/S: {download_link} pour '{release_name}'.")
            try:
                # Première requête sans suivre les redirections pour inspecter
                # Utilisation d'un User-Agent commun pour éviter blocages potentiels
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                initial_response = requests.get(download_link, timeout=15, allow_redirects=False, headers=headers)

                # Ne pas lever d'exception immédiatement pour pouvoir inspecter les redirections vers magnet
                if initial_response.status_code >= 400:
                     # Si c'est une erreur client/serveur directe, lever l'exception
                    initial_response.raise_for_status()


                if initial_response.is_redirect or initial_response.is_permanent_redirect:
                    location_header = initial_response.headers.get('Location')
                    current_app.logger.info(f"L'URL Prowlarr a redirigé vers: {location_header}")
                    if location_header and location_header.startswith("magnet:"):
                        torrent_hash, error_msg_add = add_magnet_and_get_hash_robustly(
                            location_header,
                            label=label_for_rtorrent,
                            destination_path=target_download_path
                        )
                    elif location_header:
                        # Si c'est une autre redirection HTTP, la suivre une fois.
                        current_app.logger.info(f"Suivi de la redirection HTTP vers: {location_header}")
                        final_response = requests.get(location_header, timeout=20, headers=headers, stream=True) # stream=True ici aussi
                        final_response.raise_for_status()
                        # Traiter le contenu de final_response
                        content_type = final_response.headers.get('Content-Type', '').lower()
                        content_disposition = final_response.headers.get('Content-Disposition', '')
                        is_torrent_content_type = 'application/x-bittorrent' in content_type or 'application/octet-stream' in content_type
                        is_torrent_filename = '.torrent' in content_disposition.lower()

                        if not (is_torrent_content_type or is_torrent_filename):
                            raise ValueError(f"Après redirection, Content-Type ('{content_type}') ou nom de fichier ('{content_disposition}') inattendu pour un .torrent.")

                        torrent_content_bytes = final_response.content
                        if not torrent_content_bytes:
                            raise ValueError("Le contenu du fichier .torrent téléchargé (après redirection) est vide.")
                        current_app.logger.info(f"Fichier .torrent téléchargé après redirection ({len(torrent_content_bytes)} octets).")
                        current_app.logger.info(f"Contenu du torrent (après redir) envoyé à rtorrent (premiers 500 octets): {torrent_content_bytes[:500]}")
                        torrent_hash, error_msg_add = add_torrent_data_and_get_hash_robustly(
                            torrent_content_bytes,
                            release_name,
                            label=label_for_rtorrent,
                            destination_path=target_download_path
                        )
                    else:
                        raise ValueError("Redirection sans en-tête 'Location'.")

                else: # Pas de redirection, la réponse initiale devrait être le fichier .torrent
                    content_type = initial_response.headers.get('Content-Type', '').lower()
                    content_disposition = initial_response.headers.get('Content-Disposition', '')
                    is_torrent_content_type = 'application/x-bittorrent' in content_type or 'application/octet-stream' in content_type
                    is_torrent_filename = '.torrent' in content_disposition.lower()

                    if not (is_torrent_content_type or is_torrent_filename):
                        # Essayer de lire une petite partie pour voir si c'est une erreur JSON de Prowlarr
                        # Important: response.content ne doit être lu qu'une fois. Si stream=True, iter_content est mieux.
                        first_chunk_content = b""
                        try:
                            # Lire le premier chunk pour l'inspection
                            chunk_iterator = initial_response.iter_content(chunk_size=1024)
                            first_chunk = next(chunk_iterator)
                            first_chunk_content = first_chunk

                            if first_chunk.strip().startswith(b"{"):
                                # Tenter de reconstituer le corps pour l'analyse JSON
                                full_body_str = first_chunk.decode('utf-8', errors='replace')
                                for next_chunk in chunk_iterator:
                                    full_body_str += next_chunk.decode('utf-8', errors='replace')

                                potential_error = json.loads(full_body_str)
                                if potential_error.get("error"):
                                    raise ValueError(f"Prowlarr (ou le lien direct) a retourné une erreur JSON: {potential_error.get('error')}")
                                # Si ce n'est pas une erreur JSON structurée, mais que le type de contenu est mauvais
                                raise ValueError(f"Content-Type ('{content_type}') ou nom de fichier ('{content_disposition}') inattendu pour un .torrent direct.")
                            else: # Pas JSON, mais mauvais type de contenu
                                raise ValueError(f"Content-Type ('{content_type}') ou nom de fichier ('{content_disposition}') inattendu pour un .torrent direct. Début du contenu: {first_chunk[:100]}")
                        except StopIteration: # Fichier vide
                             raise ValueError("Le contenu du fichier .torrent téléchargé est vide (StopIteration lors de la vérification).")
                        except ValueError as ve: # Relancer l'erreur ValueError (soit JSON error, soit type inattendu, soit vide)
                            raise ve
                        except Exception as e_chunk: # Autre erreur lors de la lecture du chunk
                            current_app.logger.warning(f"Problème lors de la vérification du Content-Type/nom de fichier pour {download_link}: {e_chunk}. Tentative de traitement comme .torrent quand même.")
                            # Si une erreur se produit ici, response.content pourrait déjà être lu ou partiellement lu.
                            # Il est plus sûr de lire response.content après ce bloc si on ne l'a pas déjà fait.
                            # Pour être sûr, on reconstruit si on a lu des chunks
                            if first_chunk_content:
                                torrent_content_bytes = first_chunk_content + b"".join(initial_response.iter_content(chunk_size=1024*1024))
                            else: # Si iter_content n'a pas été appelé
                                torrent_content_bytes = initial_response.content
                    else: # Type de contenu ou nom de fichier OK
                        torrent_content_bytes = initial_response.content


                    if not torrent_content_bytes: # Vérification finale
                        raise ValueError("Le contenu du fichier .torrent téléchargé est vide.")
                    current_app.logger.info(f"Fichier .torrent téléchargé directement ({len(torrent_content_bytes)} octets).")
                    current_app.logger.info(f"Contenu du torrent (direct) envoyé à rtorrent (premiers 500 octets): {torrent_content_bytes[:500]}")
                    torrent_hash, error_msg_add = add_torrent_data_and_get_hash_robustly(
                        torrent_content_bytes,
                        release_name,
                        label=label_for_rtorrent,
                        destination_path=target_download_path
                    )

            except requests.exceptions.Timeout:
                error_msg_add = f"Timeout lors de la communication avec Prowlarr/URL pour '{release_name}'."
            except requests.exceptions.RequestException as e_req:
                error_msg_add = f"Erreur de communication avec Prowlarr/URL pour '{release_name}': {e_req}"
            except ValueError as e_val:
                error_msg_add = f"Erreur de traitement du lien Prowlarr pour '{release_name}': {str(e_val)}"

            if error_msg_add:
                 current_app.logger.error(error_msg_add)

        # Traitement commun après tentative d'ajout (magnet ou données)
        if error_msg_add or not torrent_hash:
            final_error_msg = error_msg_add or f"Erreur inconnue lors de l'ajout du torrent '{release_name}' ou de la récupération du hash."
            current_app.logger.error(f"Échec final de l'ajout/récupération hash pour '{release_name}'. Message: {final_error_msg}")
            return jsonify({'status': 'error', 'message': final_error_msg}), 500

        current_app.logger.info(f"Torrent '{release_name}' ajouté. Hash '{torrent_hash}' récupéré. Tentative de mapping.")

        # Suite du mapping (inchangée)
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

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

# Imports nécessaires pour la nouvelle route download_torrent
from flask import Response, stream_with_context # stream_with_context might not be needed for the new proxy
# requests est déjà importé plus haut dans le fichier
# current_app est déjà importé
# login_required est déjà importé
# request est déjà importé via 'from flask import ..., request, ...'

@search_ui_bp.route('/download_torrent_proxy')
@login_required
def download_torrent_proxy():
    """
    Acts as an intelligent proxy to download a .torrent file.
    Uses special handling for YGGTorrent (cookies, user-agent) and standard requests for others.
    """
    torrent_download_url = request.args.get('url')
    indexer_id_arg = request.args.get('indexer_id')
    # release_name_arg = request.args.get('release_name', 'downloaded') # Optionnel, pour nommer le fichier

    if not torrent_download_url or not indexer_id_arg:
        current_app.logger.error("Proxy download: 'url' ou 'indexer_id' manquant dans les arguments.")
        return Response("Arguments 'url' et 'indexer_id' manquants.", status=400)

    # Construire le nom de fichier (peut être amélioré plus tard si besoin)
    filename = "downloaded.torrent"
    # Tentative d'extraire un nom de fichier plus pertinent de l'URL si possible
    # Ceci est une heuristique simple et pourrait être affinée
    try:
        if 'title=' in torrent_download_url.lower(): # Souvent utilisé par Prowlarr
            extracted_name = torrent_download_url.split('title=')[1].split('&')[0]
            # Nettoyer un peu le nom et s'assurer qu'il finit par .torrent
            # Éviter les caractères invalides pour les noms de fichiers si nécessaire (non fait ici pour la simplicité)
            filename = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in extracted_name)
            if not filename.lower().endswith('.torrent'):
                filename += ".torrent"
            if len(filename) > 60: # Limiter la longueur
                 filename = filename[:56] + ".torrent"

        elif '/' in torrent_download_url:
            potential_name = torrent_download_url.split('/')[-1]
            if potential_name and ('.torrent' in potential_name.lower() or not '.' in potential_name): # s'il semble être un nom de fichier
                 # Nettoyage simple
                potential_name_cleaned = "".join(c if c.isalnum() or c in ['.', '_', '-'] else '_' for c in potential_name)
                if not potential_name_cleaned.lower().endswith('.torrent'):
                    potential_name_cleaned += ".torrent"
                if len(potential_name_cleaned) > 4 and len(potential_name_cleaned) < 60 : # simple validation
                    filename = potential_name_cleaned
    except Exception as e_filename:
        current_app.logger.warning(f"Proxy download: Erreur lors de l'extraction du nom de fichier depuis {torrent_download_url}: {e_filename}. Utilisation de '{filename}'.")


    ygg_indexer_id_conf = current_app.config.get('YGG_INDEXER_ID')
    torrent_data = None
    error_message = None
    status_code = 500

    current_app.logger.info(f"Proxy download request for indexer_id: {indexer_id_arg}, url: {torrent_download_url}")

    if ygg_indexer_id_conf and str(indexer_id_arg) == str(ygg_indexer_id_conf):
        current_app.logger.info(f"Proxy download: YGG indexer ({indexer_id_arg}) detected. Using special download method.")
        ygg_cookie = current_app.config.get('YGG_COOKIE')
        ygg_user_agent = current_app.config.get('YGG_USER_AGENT')
        ygg_base_url = current_app.config.get('YGG_BASE_URL')

        if not ygg_cookie:
            error_message = "Configuration YGG_COOKIE manquante pour le téléchargement YGG."
            current_app.logger.error(error_message)
            status_code = 503 # Service Unavailable (configuration issue)
        else:
            headers = {
                'User-Agent': ygg_user_agent,
                'Cookie': ygg_cookie
            }
            # S'assurer que l'URL est absolue
            if not torrent_download_url.startswith(('http://', 'https://')):
                if not ygg_base_url:
                    error_message = "Proxy download: URL relative pour YGG mais YGG_BASE_URL non configuré."
                    current_app.logger.error(error_message)
                    return Response(error_message, status=503)
                # Supposons que torrent_download_url pourrait commencer par / si c'est un chemin relatif
                torrent_full_url = ygg_base_url.rstrip('/') + '/' + torrent_download_url.lstrip('/')
                current_app.logger.info(f"Proxy download: URL YGG relative convertie en: {torrent_full_url}")
            else:
                torrent_full_url = torrent_download_url

            try:
                current_app.logger.info(f"Proxy download: Attempting YGG download from {torrent_full_url} with User-Agent and Cookie.")
                response = requests.get(torrent_full_url, headers=headers, timeout=30, allow_redirects=True)
                response.raise_for_status()

                # Vérification du Content-Type pour YGG (peut être différent)
                content_type_ygg = response.headers.get('Content-Type', '').lower()
                current_app.logger.info(f"Proxy download: YGG response Content-Type: {content_type_ygg}")
                if not ('application/x-bittorrent' in content_type_ygg or
                        'application/octet-stream' in content_type_ygg): # Octet-stream est souvent utilisé aussi
                    # YGG pourrait retourner du HTML/JSON même avec un statut 200 si le cookie est mauvais/expiré
                    # Essayer de détecter cela si possible, mais c'est complexe sans connaître la structure exacte des erreurs YGG.
                    # Pour l'instant, on logue un avertissement si le type n'est pas celui attendu.
                    current_app.logger.warning(f"Proxy download: YGG Content-Type inattendu '{content_type_ygg}' pour {torrent_full_url}. Le fichier pourrait ne pas être un torrent valide.")
                    # On pourrait décider de rejeter ici, mais pour l'instant, on continue et on laisse le client torrent décider.

                torrent_data = response.content
                current_app.logger.info(f"Proxy download: YGG download successful, {len(torrent_data)} bytes received.")
            except requests.exceptions.RequestException as e_ygg:
                error_message = f"Erreur lors du téléchargement spécial YGG depuis {torrent_full_url}: {e_ygg}"
                current_app.logger.error(error_message)
                status_code = 502 # Bad Gateway
            except Exception as e_gen_ygg:
                error_message = f"Erreur générique inattendue (YGG) {torrent_full_url}: {e_gen_ygg}"
                current_app.logger.error(error_message, exc_info=True)
                status_code = 500
    else:
        current_app.logger.info(f"Proxy download: Standard indexer ({indexer_id_arg}). Using standard download method for {torrent_download_url}.")
        try:
            # Utilisation d'un User-Agent standard pour les autres, au cas où.
            headers_standard = {'User-Agent': current_app.config.get('YGG_USER_AGENT', 'Mozilla/5.0')}
            response = requests.get(torrent_download_url, timeout=30, allow_redirects=True, headers=headers_standard, stream=True)
            response.raise_for_status()

            content_type_standard = response.headers.get('Content-Type', '').lower()
            current_app.logger.info(f"Proxy download: Standard response Content-Type: {content_type_standard}")
            if not ('application/x-bittorrent' in content_type_standard or
                    'application/octet-stream' in content_type_standard):
                current_app.logger.warning(f"Proxy download: Standard Content-Type inattendu '{content_type_standard}' pour {torrent_download_url}. Le fichier pourrait ne pas être un torrent valide.")
                # On pourrait arrêter ici, mais pour l'instant, on continue.

            # Lire le contenu en chunks pour les fichiers potentiellement volumineux (même si les .torrent sont petits)
            # Mais comme on doit le stocker en mémoire pour `torrent_data` avant Response, on peut utiliser .content
            # Sauf si on veut streamer directement vers le client, ce qui est plus complexe avec la logique conditionnelle.
            # Pour la simplicité et vu que les .torrent sont petits, .content est ok.
            torrent_data = response.content # Si stream=True était utilisé, il faudrait itérer avec response.iter_content()
            current_app.logger.info(f"Proxy download: Standard download successful, {len(torrent_data)} bytes received.")
        except requests.exceptions.RequestException as e_std:
            error_message = f"Erreur lors du téléchargement standard depuis {torrent_download_url}: {e_std}"
            current_app.logger.error(error_message)
            status_code = 502 # Bad Gateway
        except Exception as e_gen_std:
            error_message = f"Erreur générique inattendue (Standard) {torrent_download_url}: {e_gen_std}"
            current_app.logger.error(error_message, exc_info=True)
            status_code = 500

    if error_message:
        return Response(error_message, status=status_code)

    if torrent_data:
        return Response(
            torrent_data,
            mimetype='application/x-bittorrent',
            headers={'Content-Disposition': f'attachment;filename="{filename}"'}
        )
    else:
        # Ce cas ne devrait pas être atteint si error_message est bien géré
        return Response("Impossible de récupérer les données du torrent.", status=500)


@search_ui_bp.route('/download-torrent')
@login_required
def download_torrent():
    """
    Acts as a proxy to download a .torrent file from a URL provided by Prowlarr.
    """
    torrent_url = request.args.get('url')
    release_name_arg = request.args.get('release_name')

    if not torrent_url:
        return "URL de téléchargement manquante.", 400 # Devrait être une réponse Flask, ex: Response("...", status=400) ou jsonify

    # Construire le nom de fichier
    if release_name_arg:
        filename = release_name_arg if release_name_arg.lower().endswith('.torrent') else f"{release_name_arg}.torrent"
    else:
        # Essayer d'extraire de l'URL Prowlarr si 'file=' est présent, sinon nom par défaut
        # Exemple d'URL Prowlarr: http://...&file=MonFichier.torrent
        if 'file=' in torrent_url:
            try:
                filename = torrent_url.split('file=')[1].split('&')[0]
                if not filename.lower().endswith('.torrent'):
                    filename += ".torrent"
            except Exception:
                filename = "downloaded.torrent"
        else:
            filename = "downloaded.torrent"

    current_app.logger.info(f"Proxying .torrent download from: {torrent_url} as filename: {filename}")

    try:
        # On utilise stream=True pour ne pas charger tout le fichier en mémoire sur le serveur
        # allow_redirects=True est le défaut, ce qui est bien ici.
        # requests gérera les redirections HTTP. S'il rencontre un schéma non supporté (magnet) après redirection, il lèvera une erreur.
        req = requests.get(torrent_url, stream=True, timeout=30) # Augmentation du timeout pour être sûr
        req.raise_for_status() # Lève une exception si le statut n'est pas 200-299

        # Vérifier si le Content-Type de la réponse finale est bien un torrent
        # Ceci est une protection supplémentaire. Si Prowlarr/indexer renvoie du HTML/JSON d'erreur avec un statut 200, on le bloque.
        content_type_final = req.headers.get('Content-Type', '').lower()
        if not ('application/x-bittorrent' in content_type_final or
                'application/octet-stream' in content_type_final or # Certains serveurs utilisent octet-stream
                filename.endswith('.torrent')): # Si le nom de fichier final (après extraction) se termine par .torrent
            current_app.logger.warning(f"Proxy download: Content-Type inattendu '{content_type_final}' pour {torrent_url} (filename: {filename}). Arrêt.")
            # On pourrait essayer de lire un peu pour voir si c'est une erreur JSON/HTML connue, mais pour l'instant, on est strict.
            return Response(f"Contenu inattendu reçu de l'URL distante. Type: {content_type_final}", status=502) # Bad Gateway

        # On renvoie la réponse au navigateur
        return Response(
            stream_with_context(req.iter_content(chunk_size=1024)),
            headers={
                'Content-Type': 'application/x-bittorrent', # On force le type pour le client
                'Content-Disposition': f'attachment; filename="{filename}"'
            }
        )

    except requests.exceptions.InvalidSchema as e_schema:
        # Spécifiquement pour les cas où une redirection mène à un magnet:
        current_app.logger.error(f"Erreur de schéma (souvent magnet) lors du téléchargement du .torrent depuis {torrent_url}: {e_schema}")
        return Response(f"Impossible de télécharger : le lien pointe vers un type non supporté (ex: magnet) : {e_schema}", status=400)
    except requests.exceptions.RequestException as e:
        current_app.logger.error(f"Erreur lors du téléchargement du .torrent depuis {torrent_url}: {e}")
        # Renvoyer l'erreur de manière plus structurée, peut-être en fonction du type d'erreur 'e'
        status_code = 502 # Bad Gateway par défaut pour les erreurs de requête vers un autre serveur
        if isinstance(e, requests.exceptions.HTTPError):
            status_code = e.response.status_code if e.response is not None else 500
        elif isinstance(e, requests.exceptions.ConnectTimeout) or isinstance(e, requests.exceptions.ReadTimeout):
            status_code = 504 # Gateway Timeout

        return Response(f"Impossible de télécharger le fichier .torrent : {e}", status=status_code)
    except Exception as ex_generic:
        current_app.logger.error(f"Erreur générique inattendue lors du téléchargement du .torrent {torrent_url}: {ex_generic}", exc_info=True)
        return Response(f"Erreur serveur inattendue lors de la tentative de téléchargement.", status=500)

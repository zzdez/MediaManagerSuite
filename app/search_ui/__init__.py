# app/search_ui/__init__.py

import logging
from flask import Blueprint, render_template, request, flash, jsonify, Response, stream_with_context, current_app
from app.auth import login_required
from config import Config
from app.utils import arr_client
from Levenshtein import distance as levenshtein_distance
from app.utils.arr_client import parse_media_name
from guessit import guessit
from app.utils.prowlarr_client import search_prowlarr
from app.utils.config_manager import load_search_categories

# 1. Définition du Blueprint (seul code global avec les imports "sûrs")
search_ui_bp = Blueprint(
    'search_ui',
    __name__,
    template_folder='templates',
    static_folder='static'
)

# 2. Toutes les routes. Les imports "à risque" sont maintenant DANS les fonctions.

@search_ui_bp.route('/', methods=['GET'])
@login_required
def search_page():
    """Affiche la page de recherche principale."""
    return render_template('search_ui/search.html')

# --- API Routes ---

@search_ui_bp.route('/api/prowlarr/search', methods=['POST'])
@login_required
def prowlarr_search():
    data = request.get_json()
    query = data.get('query')
    if not query:
        return jsonify({"error": "La requête est vide."}), 400

    search_type = data.get('search_type', 'sonarr')
    search_config = load_search_categories()
    categories_to_filter = set(search_config.get(f"{search_type}_categories", []))

    logging.info(f"Recherche Prowlarr large pour '{query}'...")
    raw_results = search_prowlarr(query=query, lang=data.get('lang'))

    if raw_results is None:
        return jsonify({"error": "Erreur de communication avec Prowlarr."}), 500
    
    logging.info(f"Prowlarr a retourné {len(raw_results)} résultats bruts. Application du filtre local...")

    if not categories_to_filter:
        logging.warning(f"Aucune catégorie configurée pour '{search_type}'. Aucun filtre par catégorie appliqué.")
        filtered_by_category = raw_results
    else:
        filtered_by_category = []
        for result in raw_results:
            result_categories = {cat.get('id') for cat in result.get('categories', [])}
            if not categories_to_filter.isdisjoint(result_categories):
                filtered_by_category.append(result)
    
    logging.info(f"{len(filtered_by_category)} résultats après filtrage par catégorie.")
    
    # === BLOC DE FILTRAGE AVANCÉ AMÉLIORÉ ===
    quality = data.get('quality')
    codec = data.get('codec')
    source = data.get('source')
    
    if not any([quality, codec, source]):
        current_app.logger.info("Aucun filtre avancé spécifié. Retour des résultats filtrés par catégorie.")
        return jsonify(filtered_by_category)

    from guessit import guessit
    final_results = []
    for result in filtered_by_category:
        title = result.get('title', '')
        parsed = guessit(title)
        
        # Filtre Qualité (plus flexible)
        if quality:
            quality_val = quality.replace('p', '')
            screen_size = str(parsed.get('screen_size', ''))
            if quality_val not in screen_size:
                continue

        # Filtre Codec (avec alias)
        if codec:
            video_codec = parsed.get('video_codec', '').lower()
            codec_aliases = {
                'x265': ['x265', 'hevc'],
                'x264': ['x264', 'avc'],
                'av1': ['av1']
            }
            if not any(alias in video_codec for alias in codec_aliases.get(codec, [codec])):
                continue

        # Filtre Source
        if source and source.lower() not in parsed.get('source', '').lower():
            continue
        
        final_results.append(result)
    
    logging.info(f"{len(final_results)} résultats après filtrage avancé.")
    return jsonify(final_results)


@search_ui_bp.route('/api/search/lookup', methods=['POST'])
def api_search_lookup():
    data = request.get_json()
    search_term = data.get('term')
    media_type = data.get('media_type')
    media_id = data.get('media_id') # Nouveau champ pour la recherche par ID

    if not media_type or (not search_term and not media_id):
        return jsonify({'error': 'Titre ou ID du média requis.'}), 400

    final_results = []
    clean_title = ""

    # Cas 1: Recherche par ID (prioritaire)
    if media_id:
        current_app.logger.info(f"Recherche par ID: {media_id}, Type: {media_type}")
        # Note: Cette partie nécessite que vos clients Arr puissent chercher par ID externe.
        # On simule un résultat pour l'instant, en attendant d'avoir la bonne fonction.
        # Pour que cela marche, il faudra une fonction comme `get_sonarr_series_by_tvdbid`
        if media_type == 'tv':
            # Simuler une recherche qui retourne un seul item
            api_response = arr_client.search_sonarr_by_title(f"tvdb:{media_id}")
            if api_response: final_results = api_response
        elif media_type == 'movie':
            api_response = arr_client.search_radarr_by_title(f"tmdb:{media_id}")
            if api_response: final_results = api_response

        if final_results:
            final_results[0]['is_best_match'] = True # L'ID est toujours le meilleur résultat
            clean_title = final_results[0].get('title', '')


    # Cas 2: Recherche par Titre
    elif search_term:
        current_app.logger.info(f"Recherche par Titre: {search_term}, Type: {media_type}")
        parsed_info = parse_media_name(search_term)
        clean_title = parsed_info.get('title', search_term).lower()
        year = parsed_info.get('year')

        api_response = []
        if media_type == 'tv':
            api_response = arr_client.search_sonarr_by_title(clean_title)
        elif media_type == 'movie':
            api_response = arr_client.search_radarr_by_title(clean_title)

        if api_response:
            scored_results = []
            for item in api_response:
                item_title = item.get('title', '').lower()
                score = levenshtein_distance(clean_title, item_title)
                if clean_title == item_title: score -= 10
                if year and item.get('year') and year != item.get('year'): score += 20
                scored_results.append({'score': score, 'data': item})

            sorted_results = sorted(scored_results, key=lambda x: x['score'])
            final_results = [result['data'] for result in sorted_results]

            if final_results:
                final_results[0]['is_best_match'] = True

    return jsonify({
        'results': final_results,
        'cleaned_query': clean_title or search_term
    })
    
# Dans app/search_ui/__init__.py, remplacez SEULEMENT cette fonction :

@search_ui_bp.route('/api/enrich/details', methods=['POST'])
def enrich_details():
    from app.utils.tvdb_client import CustomTVDBClient
    from app.utils.tmdb_client import TheMovieDBClient
    from flask import current_app

    data = request.get_json()
    media_id = data.get('media_id')
    media_type = data.get('media_type')

    if not media_id or not media_type:
        return jsonify({'error': 'ID ou type de média manquant'}), 400

    try:
        if media_type == 'tv':
            client = CustomTVDBClient()
            details = client.get_series_details_by_id(media_id, lang='fra')
            if not details: return jsonify({'error': 'Série non trouvée'}), 404

            # === LA CORRECTION FINALE ET DÉCISIVE EST ICI ===
            # On ne reconstruit PAS l'URL. On prend celle fournie par la bibliothèque.
            poster_url = details.get('image', '') 
            
            formatted_details = {
                'id': details.get('id'),
                'title': details.get('seriesName'),
                'year': details.get('year'),
                'overview': details.get('overview'),
                'poster': poster_url, # L'URL est maintenant correcte.
                'status': details.get('status', {}).get('name', 'Inconnu')
            }
            return jsonify(formatted_details)

        elif media_type == 'movie':
            client = TheMovieDBClient()
            details = client.get_movie_details(media_id, lang='fr-FR')
            if not details: return jsonify({'error': 'Film non trouvé'}), 404

            # La sortie du client TMDB est déjà parfaite, on la transmet.
            return jsonify(details)

    except Exception as e:
        current_app.logger.error(f"Erreur dans enrich_details: {e}", exc_info=True)
        return jsonify({'error': f"Erreur serveur : {e}"}), 500

# NOTE: Les autres routes de l'ancien fichier 'routes.py' comme '/download-and-map', etc.
# doivent aussi être migrées ici en utilisant le même pattern d'imports locaux si elles
# sont toujours utilisées. Pour l'instant, je me concentre sur le strict nécessaire pour
# faire fonctionner la recherche et la modale.

# =====================================================================
# ROUTES ADDITIONNELLES RESTAURÉES
# =====================================================================

@search_ui_bp.route('/check_media_status', methods=['POST'])
@login_required
def check_media_status_api():
    # Imports locaux
    from app.utils.media_status_checker import check_media_status as util_check_media_status

    data = request.json
    title = data.get('title')

    if not title:
        return jsonify({'text': 'Titre manquant', 'status_class': 'text-danger'}), 400

    try:
        # 1. On récupère le dictionnaire complet depuis notre fonction utilitaire
        status_info = util_check_media_status(release_title=title)

        # 2. On prépare le champ 'text' pour les cas simples (compatibilité)
        status_info['text'] = status_info.get('details', status_info.get('status', 'Indéterminé'))
        
        # 3. On s'assure que la classe CSS est présente
        badge_color = status_info.get('badge_color', 'secondary')
        status_class_map = {
            'success': 'text-success', 'warning': 'text-warning',
            'danger': 'text-danger', 'secondary': 'text-body-secondary',
            'dark': 'text-body-secondary'
        }
        status_info['status_class'] = status_class_map.get(badge_color, 'text-body-secondary')

        # 4. On renvoie le dictionnaire ENTIER, qui inclut 'status_details' s'il existe
        return jsonify(status_info)

    except Exception as e:
        current_app.logger.error(f"Erreur API dans /check_media_status pour '{title}': {e}", exc_info=True)
        return jsonify({'text': 'Erreur serveur interne', 'status_class': 'text-danger'}), 500



@search_ui_bp.route('/api/prepare_mapping_details', methods=['POST'])
@login_required
def prepare_mapping_details():
    # Imports locaux
    from app.utils.arr_client import parse_media_name, search_sonarr_by_title, search_radarr_by_title
    # Note: L'utilisation de CustomTVDBClient et TheMovieDBClient est retirée au profit du nouveau système de lazy loading

    data = request.json
    release_title = data.get('title')

    if not release_title:
        return jsonify({'error': 'Titre manquant'}), 400

    parsed_info = parse_media_name(release_title)
    media_type = 'series' if parsed_info['type'] == 'tv' else 'movie'

    candidates = []
    if media_type == 'series':
        candidates = search_sonarr_by_title(parsed_info['title'])
    else: # 'movie'
        candidates = search_radarr_by_title(parsed_info['title'])

    # Ceci retourne la liste des candidats non-enrichis, qui sera enrichie côté client au besoin.
    return render_template('search_ui/_mapping_selection_list.html', candidates=candidates)


@search_ui_bp.route('/download-and-map', methods=['POST'])
@login_required
def download_and_map():
    # Imports locaux pour cette fonction spécifique
    import requests
    from app.utils.rtorrent_client import add_torrent_data_and_get_hash_robustly, add_magnet_and_get_hash_robustly
    from app.utils.mapping_manager import add_or_update_torrent_in_map
    from urllib.parse import urlparse

    logger = current_app.logger

    data = request.get_json()
    release_name = data.get('releaseName')
    download_link = data.get('downloadLink')
    indexer_id = data.get('indexerId')
    guid = data.get('guid')
    instance_type = data.get('instanceType') # 'tv' ou 'movie'
    media_id = data.get('mediaId')

    if not all([release_name, download_link, instance_type, media_id]):
        logger.error("Requête /download-and-map invalide, données manquantes.")
        return jsonify({'status': 'error', 'message': 'Données manquantes dans la requête.'}), 400

    internal_instance_type = 'sonarr' if instance_type == 'tv' else 'radarr'
    torrent_hash = None

    try:
        logger.info(f"Début du traitement pour '{release_name}'")

        # 1. Déterminer si c'est un magnet ou un lien .torrent
        if download_link.startswith('magnet:'):
            logger.info("Lien magnet détecté. Envoi à rTorrent.")
            torrent_hash = add_magnet_and_get_hash_robustly(download_link)
        else:
            logger.info("Lien .torrent détecté. Utilisation du proxy de téléchargement.")
            proxy_url = f"http://127.0.0.1:{current_app.config.get('FLASK_RUN_PORT', 5001)}/search/download_torrent_proxy"
            params = {'url': download_link, 'release_name': release_name, 'indexer_id': indexer_id, 'guid': guid}
            
            # On simule une session pour passer les cookies de login
            session_cookie_name = current_app.config.get("SESSION_COOKIE_NAME", "session")
            cookies = {session_cookie_name: request.cookies.get(session_cookie_name)}

            response = requests.get(proxy_url, params=params, cookies=cookies, timeout=60)
            response.raise_for_status()
            
            torrent_content = response.content
            logger.info(f"{len(torrent_content)} bytes de données de torrent reçues du proxy.")
            torrent_hash = add_torrent_data_and_get_hash_robustly(
                torrent_content_bytes=torrent_content,
                filename_for_rtorrent=f"{release_name}.torrent",
                label=internal_instance_type # <--- AJOUTÉ : On passe 'sonarr' ou 'radarr'
            )

        # 2. Vérifier si on a un hash VALIDE (une chaîne de caractères) avant de sauvegarder
        if torrent_hash and isinstance(torrent_hash, str):
            logger.info(f"Torrent ajouté avec succès. Hash : {torrent_hash}. Sauvegarde du mapping.")
            add_or_update_torrent_in_map(
                torrent_hash=torrent_hash,
                release_name=release_name,
                app_type=internal_instance_type,      # CORRIGÉ: renommé en 'app_type'
                target_id=str(media_id),              # CORRIGÉ: renommé en 'target_id'
                label=internal_instance_type,         # AJOUTÉ: le paramètre 'label' est obligatoire
                seedbox_download_path="N/A_added_from_search" # AJOUTÉ: le paramètre 'seedbox_download_path' est obligatoire
            )
            return jsonify({'status': 'success', 'message': 'Torrent ajouté et mappé avec succès.'})
        else:
            raise Exception("Le hash du torrent n'a pas pu être récupéré depuis rTorrent.")

    except Exception as e:
        logger.error(f"Erreur majeure dans /download-and-map pour '{release_name}': {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f"Erreur serveur inattendue: {str(e)}"}), 500
# =====================================================================
# ROUTES DE PROXY DE TÉLÉCHARGEMENT RESTAURÉES
# =====================================================================

@search_ui_bp.route('/download_torrent_proxy')
@login_required
def download_torrent_proxy():
    # Imports locaux
    import requests

    url = request.args.get('url')
    release_name = request.args.get('release_name', 'download.torrent')
    indexer_id = request.args.get('indexer_id')
    guid = request.args.get('guid')

    if not all([url, release_name, indexer_id, guid]):
        current_app.logger.error(f"Proxy download: Paramètres manquants.")
        return Response("Erreur: Paramètres manquants.", status=400)

    ygg_indexer_id = current_app.config.get('YGG_INDEXER_ID')
    final_filename = f"{release_name.replace(' ', '_')}.torrent"

    try:
        if str(ygg_indexer_id) == str(indexer_id):
            ygg_cookie = current_app.config.get('YGG_COOKIE')
            ygg_user_agent = current_app.config.get('YGG_USER_AGENT')
            ygg_base_url = current_app.config.get('YGG_BASE_URL')

            if not all([ygg_cookie, ygg_user_agent, ygg_base_url]):
                raise ValueError("Configuration YGG manquante.")

            release_id_ygg = guid.split('?id=')[1].split('&')[0]
            final_ygg_download_url = f"{ygg_base_url.rstrip('/')}/engine/download_torrent?id={release_id_ygg}"
            headers = {'User-Agent': ygg_user_agent, 'Cookie': ygg_cookie}
            response = requests.get(final_ygg_download_url, headers=headers, timeout=45, allow_redirects=True)
        else:
            standard_user_agent = current_app.config.get('YGG_USER_AGENT', 'Mozilla/5.0')
            headers = {'User-Agent': standard_user_agent}
            response = requests.get(url, headers=headers, timeout=45, allow_redirects=True)

        response.raise_for_status()

        content_type = response.headers.get('Content-Type', '').lower()
        if 'application/x-bittorrent' not in content_type and 'application/octet-stream' not in content_type:
            raise ValueError(f"La réponse n'est pas un fichier .torrent valide. Content-Type: '{content_type}'.")

        return Response(
            response.content,
            mimetype='application/x-bittorrent',
            headers={'Content-Disposition': f'attachment;filename="{final_filename}"'}
        )
    except Exception as e:
        current_app.logger.error(f"Proxy download: Erreur pour '{release_name}': {e}", exc_info=True)
        return Response(f"Une erreur est survenue lors du proxy de téléchargement: {e}", status=500)

@search_ui_bp.route('/api/add/manual', methods=['POST'])
@login_required
def manual_add_media():
    data = request.get_json()
    media_id = data.get('media_id')
    media_type = data.get('media_type') # 'tv' ou 'movie'
    title = data.get('title', '') # Titre optionnel

    if not media_id or not media_type:
        return jsonify({'status': 'error', 'message': 'ID du média ou type manquant.'}), 400

    try:
        # Récupérer les configurations par défaut
        if media_type == 'tv':
            root_folder = current_app.config.get('DEFAULT_SONARR_ROOT_FOLDER')
            profile_id = current_app.config.get('DEFAULT_SONARR_PROFILE_ID')
            lang_profile_id = current_app.config.get('DEFAULT_SONARR_LANGUAGE_PROFILE_ID')
            if not all([root_folder, profile_id, lang_profile_id]):
                raise ValueError("Configuration Sonarr par défaut manquante.")

            # Ajoute la série via son TVDB ID
            added_item = arr_client.add_new_series_to_sonarr(
                tvdb_id=int(media_id),
                title=title, # Le titre est surtout pour le log, Sonarr se base sur l'ID
                quality_profile_id=profile_id,
                language_profile_id=lang_profile_id,
                root_folder_path=root_folder
            )

        elif media_type == 'movie':
            root_folder = current_app.config.get('DEFAULT_RADARR_ROOT_FOLDER')
            profile_id = current_app.config.get('DEFAULT_RADARR_PROFILE_ID')
            if not all([root_folder, profile_id]):
                raise ValueError("Configuration Radarr par défaut manquante.")

            # Ajoute le film via son TMDb ID
            added_item = arr_client.add_new_movie_to_radarr(
                tmdb_id=int(media_id),
                title=title,
                quality_profile_id=profile_id,
                root_folder_path=root_folder
            )
        else:
             return jsonify({'status': 'error', 'message': 'Type de média non supporté.'}), 400

        if added_item and added_item.get('id'):
            return jsonify({
                'status': 'success',
                'message': f"'{added_item.get('title')}' ajouté avec succès à {media_type.capitalize()}!",
                'added_item': added_item
            })
        else:
            raise Exception("L'ajout a échoué. Réponse invalide de l'API Arr.")

    except Exception as e:
        current_app.logger.error(f"Erreur durant l'ajout manuel: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500

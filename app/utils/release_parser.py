# Fichier : app/utils/release_parser.py

from guessit import guessit
from unidecode import unidecode
import re
from flask import current_app
from app.utils.config_manager import load_search_filter_aliases

# --- LISTE DE MOTS-CLÉS COMPLÈTE ---
# ... (inchangé)
COLLECTION_KEYWORDS = [
    'integrale', 'integral', 'the complete series', 'collection',
    'boxset', 'box set', 'saga', 'pack', 'duo', 'duology', 'trilogie',
    'trilogy', 'quadrilogie', 'quadrilogy', 'pentalogie', 'pentalogy',
    'hexalogie', 'hexalogy', 'heptalogie', 'heptalogy', 'anthology',
    'chronicles', 'universe'
]

def _normalize_string(text):
    """Helper function to lowercase and remove accents from a string."""
    return unidecode(text).lower()

def parse_release_data(release_name):
    """
    Analyse un nom de release avec guessit, le nettoie et normalise les langues
    en utilisant les alias de la configuration.
    Retourne un dictionnaire structuré et fiable.
    """
    guess = guessit(release_name)
    title_lower_normalized = _normalize_string(release_name)

    # Initialisation de notre objet de données propres
    parsed_data = {
        'quality': guess.get('screen_size'),
        'codec': guess.get('video_codec'),
        'source': guess.get('source'),
        'year': guess.get('year'),
        'season': guess.get('season'),
        'episode': guess.get('episode'),
        'language': None,
        'release_group': None,
        'is_episode': False,
        'is_season_pack': False,
        'is_collection': False
    }

    # --- NOUVELLE LOGIQUE DE LANGUE AVEC ALIAS ---
    # 1. Charger les alias de langue depuis la configuration
    # Doit être dans un contexte d'application pour fonctionner
    with current_app.app_context():
        lang_aliases = load_search_filter_aliases().get('lang', {})

    # 2. Extraire la langue de guessit
    detected_lang = None
    if 'language' in guess:
        lang_obj = guess['language']
        if isinstance(lang_obj, list):
            lang_obj = lang_obj[0]
        detected_lang = str(lang_obj).lower()

    # 3. Normaliser la langue en utilisant les alias
    if detected_lang:
        normalized_lang = None
        for canonical_lang, aliases in lang_aliases.items():
            if detected_lang in aliases:
                normalized_lang = canonical_lang
                break
        # Si aucune correspondance n'est trouvée, utiliser la langue détectée telle quelle
        parsed_data['language'] = normalized_lang or detected_lang

    # --- Logique de Release Group Améliorée (Nettoyage) ---
    if 'release_group' in guess:
        raw_group = guess['release_group']
        # Nettoie les informations additionnelles (ex: "TFA (Compte a rebours)")
        clean_group = raw_group.split('(')[0].strip()
        parsed_data['release_group'] = clean_group

    # --- NOUVELLE LOGIQUE DE DÉTECTION DE PACK ---
    # On vérifie dans un ordre de priorité : Collection > Pack de Saison > Épisode

    # 1. Détecter les collections/intégrales en premier
    if any(keyword in title_lower_normalized for keyword in COLLECTION_KEYWORDS):
        parsed_data['is_collection'] = True

    # 2. Sinon, vérifier si c'est un pack de saison
    elif parsed_data['season'] is not None and parsed_data['episode'] is None:
        parsed_data['is_season_pack'] = True

    # 3. Sinon, c'est un épisode unique
    elif parsed_data['episode'] is not None:
        parsed_data['is_episode'] = True

    return parsed_data

# Fichier : app/utils/release_parser.py

from guessit import guessit
from unidecode import unidecode # Import de la nouvelle bibliothèque
import re

# --- LISTE DE MOTS-CLÉS COMPLÈTE ---
# Basée sur les recherches de l'utilisateur. Normalisée (lowercase, sans accents).
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
    Analyse un nom de release avec guessit et le nettoie pour le filtrage.
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

    # --- Logique de Langue Améliorée ---
    if 'language' in guess:
        # 'language' peut être un objet ou une liste, on le traite
        lang_obj = guess['language']
        if isinstance(lang_obj, list):
            # Prend la première langue de la liste pour simplifier
            lang_obj = lang_obj[0]
        parsed_data['language'] = str(lang_obj).lower()

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

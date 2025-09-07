# Fichier : test_prowlarr_filtering.py
# Description : Ce script est un outil de test autonome pour interroger l'API de Prowlarr
#               et analyser les résultats avec la bibliothèque 'guessit'.
#               Il fonctionne en dehors de l'application Flask mais utilise le même fichier .env
#               pour la configuration.
#
# Utilisation : python test_prowlarr_filtering.py

import os
import requests
import json
from dotenv import load_dotenv
from guessit import guessit

# --- CONFIGURATION ---

# Charger les variables d'environnement depuis le fichier .env à la racine du projet
print("Chargement des variables d'environnement...")
load_dotenv()

PROWLARR_API_URL = os.environ.get("PROWLARR_API_URL")
PROWLARR_API_KEY = os.environ.get("PROWLARR_API_KEY")

# Catégories par défaut (similaires à celles de l'application)
# Vous pouvez les ajuster pour vos tests.
# 2000 = Films, 5000 = Séries TV, 5040 = Séries TV HD
CATEGORIES_RADARR = [2000]
CATEGORIES_SONARR = [5000, 5040]

# Critères de filtrage pour le test
FILTER_CRITERIA = {
    'screen_size': '1080p',
    'languages': ['french', 'multi']
}

# --- FONCTIONS ---

def search_prowlarr(query, categories):
    """Interroge l'API de Prowlarr avec une recherche et des catégories spécifiques."""
    if not all([PROWLARR_API_URL, PROWLARR_API_KEY]):
        print("ERREUR : PROWLARR_API_URL ou PROWLARR_API_KEY ne sont pas définis dans le fichier .env.")
        return None

    params = {
        'apikey': PROWLARR_API_KEY,
        'query': query,
        'cat': ','.join(map(str, categories))  # L'API Prowlarr utilise 'cat' pour les catégories
    }

    try:
        response = requests.get(f"{PROWLARR_API_URL}/api/v1/search", params=params, timeout=30)
        response.raise_for_status()  # Lève une exception pour les erreurs HTTP (4xx ou 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"ERREUR : Échec de la connexion à Prowlarr : {e}")
        return None

def search_and_analyze(query, categories):
    """Lance une recherche, analyse les résultats avec guessit et les filtre."""

    results = search_prowlarr(query, categories)

    print(json.dumps(results, indent=2))

    if results is None:
        print("La recherche Prowlarr a échoué. Arrêt du scénario.")
        return

    print(f"Succès ! Prowlarr a retourné {len(results)} résultats bruts pour '{query}'.")
    print("\n--- Analyse et Filtrage des résultats ---")

    filtered_releases = []

    for result in results:
        title = result.get('title', '')
        print("--------------------------------------------------")
        print(f"Release: {title}")

        guess = guessit(title)
        print("Guessit a trouvé :")

        # Affiche les clés pertinentes trouvées par guessit
        relevant_keys = ['year', 'language', 'screen_size', 'source', 'other', 'video_codec', 'audio_codec', 'audio_channels', 'release_group', 'season', 'episode']
        found_something = False
        for key in relevant_keys:
            if key in guess:
                print(f"  - {key}: {guess[key]}")
                found_something = True
        if not found_something:
            print("  - (Aucune information pertinente trouvée)")

        # Logique de filtrage
        lang_found = False
        if 'language' in guess:
            # 'language' peut être un objet ou une liste, on le convertit en chaîne pour la recherche
            lang_str = str(guess['language']).lower()
            if any(lang in lang_str for lang in FILTER_CRITERIA['languages']):
                lang_found = True

        if (guess.get('screen_size') == FILTER_CRITERIA['screen_size'] and lang_found):
            print(f"  -> CRITÈRES REMPLIS ({FILTER_CRITERIA['screen_size']}, {','.join(FILTER_CRITERIA['languages']).upper()})")
            filtered_releases.append(title)

    print("\n============================================================")
    print(f"--- RÉSULTATS FILTRÉS POUR '{query}' ---")
    print(f"Nombre de releases correspondant aux critères : {len(filtered_releases)}")
    print("============================================================")
    print("Titres des releases filtrées :")
    if filtered_releases:
        for release_title in filtered_releases:
            print(f"- {release_title}")
    else:
        print("(Aucune)")


def main():
    """Fonction principale qui exécute les scénarios de test."""
    if not all([PROWLARR_API_URL, PROWLARR_API_KEY]):
        print("Veuillez vous assurer que PROWLARR_API_URL et PROWLARR_API_KEY sont définis dans votre fichier .env")
        return

    print("Variables d'environnement chargées avec succès.")

    # --- Scénario 1 : Recherche de Film ---
    print("\n################################################################################")
    print(f"## DÉBUT DU SCÉNARIO : Recherche de 'D-Tox' dans les catégories {CATEGORIES_RADARR} ##")
    print("################################################################################\n")
    search_and_analyze(query="D-Tox", categories=CATEGORIES_RADARR)

    # --- Scénario 2 : Recherche de Série ---
    print("\n################################################################################")
    print(f"## DÉBUT DU SCÉNARIO : Recherche de 'Compte à rebours' dans les catégories {CATEGORIES_SONARR} ##")
    print("################################################################################\n")
    search_and_analyze(query="Compte à rebours", categories=CATEGORIES_SONARR)


if __name__ == "__main__":
    main()

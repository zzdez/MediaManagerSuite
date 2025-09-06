import os
import requests
import guessit
from dotenv import load_dotenv

def search_and_analyze(prowlarr_url, prowlarr_api_key, query, categories):
    """
    Interroge Prowlarr pour une requête donnée et des catégories spécifiques,
    puis analyse et filtre les résultats.
    """
    print("\n" + "#"*80)
    print(f"## DÉBUT DU SCÉNARIO : Recherche de '{query}' dans les catégories {categories} ##")
    print("#"*80 + "\n")

    # --- 1. Interroger Prowlarr ---
    headers = {"X-Api-Key": prowlarr_api_key}
    params = {
        "query": query,
        "cat": ",".join(map(str, categories)),  # Utilisation du paramètre 'cat'
        "type": "search"
    }

    try:
        response = requests.get(f"{prowlarr_url}/api/v1/search", headers=headers, params=params)
        response.raise_for_status()

        results = response.json()
        print(f"Succès ! Prowlarr a retourné {len(results)} résultats bruts pour '{query}'.")

        # --- 2. Analyser et Filtrer les résultats ---
        if not results:
            print("Aucun résultat à analyser.")
            return

        filtered_releases = []

        for release in results:
            title = release.get("title", "Titre non disponible")
            guess = guessit.guessit(title)

            print("-" * 50)
            print(f"Release: {title}")
            print("Guessit a trouvé :")
            for key, value in guess.items():
                if key not in ['title', 'type']:
                    if key == 'language' and hasattr(value, '__iter__') and not isinstance(value, str):
                         print(f"  - {key}: {', '.join(l.name for l in value)}")
                    elif hasattr(value, 'name'):
                         print(f"  - {key}: {value.name}")
                    else:
                         print(f"  - {key}: {value}")

            screen_size = guess.get('screen_size')
            language = guess.get('language')

            lang_names = []
            if hasattr(language, '__iter__') and not isinstance(language, str):
                lang_names = [l.name.upper() for l in language]
            elif hasattr(language, 'name'):
                lang_names = [language.name.upper()]

            if screen_size == '1080p' and ('FRENCH' in lang_names or 'MULTI' in lang_names):
                filtered_releases.append(release)
                print("  -> CRITÈRES REMPLIS (1080p, FRENCH/MULTi)")

        print("-" * 50)

        # --- 3. Afficher les résultats finaux filtrés ---
        print("\n" + "="*60)
        print(f"--- RÉSULTATS FILTRÉS POUR '{query}' ---")
        print(f"Nombre de releases correspondant aux critères : {len(filtered_releases)}")
        print("="*60)

        if filtered_releases:
            print("Titres des releases filtrées :")
            for release in filtered_releases:
                print(f"- {release['title']}")
        else:
            print("Aucune release ne correspond aux critères de filtrage (1080p et langue FRENCH/MULTi).")

    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de la requête vers Prowlarr pour '{query}': {e}")
    except Exception as e:
        print(f"Une erreur inattendue est survenue pour '{query}': {e}")


def main():
    """Fonction principale du script de test."""
    print("Chargement des variables d'environnement...")
    load_dotenv()

    prowlarr_url = os.getenv("PROWLARR_URL")
    prowlarr_api_key = os.getenv("PROWLARR_API_KEY")

    if not prowlarr_url or not prowlarr_api_key:
        print("Erreur : Assurez-vous que PROWLARR_URL et PROWLARR_API_KEY sont définis dans votre fichier .env")
        return

    print("Variables d'environnement chargées avec succès.")

    # --- Scénario 1: Recherche de Film ---
    movie_query = "D-Tox"
    movie_categories = [2000]
    search_and_analyze(prowlarr_url, prowlarr_api_key, movie_query, movie_categories)

    # --- Scénario 2: Recherche de Série ---
    series_query = "Compte à rebours"
    series_categories = [5000, 5040] # 5000 pour TV, 5040 pour TV HD
    search_and_analyze(prowlarr_url, prowlarr_api_key, series_query, series_categories)

if __name__ == "__main__":
    main()

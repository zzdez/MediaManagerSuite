import os
import requests
import guessit
from dotenv import load_dotenv

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

    # --- 1. Définir une Recherche Cible ---
    search_query = "Compte à rebours"
    print(f"\n--- Début de la recherche pour : '{search_query}' ---")

    # --- 2. Interroger Prowlarr ---
    headers = {
        "X-Api-Key": prowlarr_api_key
    }
    params = {
        "query": search_query,
        "categories": "2000",  # Catégorie pour les séries TV
        "type": "search"
    }

    try:
        response = requests.get(f"{prowlarr_url}/api/v1/search", headers=headers, params=params)
        response.raise_for_status()

        results = response.json()
        print(f"Succès ! Prowlarr a retourné {len(results)} résultats bruts.")

        # --- 3. Analyser et Filtrer les résultats ---
        print("\n--- Analyse et Filtrage des résultats ---")
        if not results:
            print("Aucun résultat à analyser.")
            return

        filtered_releases = []

        for release in results:
            title = release.get("title", "Titre non disponible")
            guess = guessit.guessit(title)

            # Affichage détaillé pour chaque release
            print("-" * 50)
            print(f"Release: {title}")
            print("Guessit a trouvé :")
            # Afficher les détails de guessit de manière propre
            for key, value in guess.items():
                if key not in ['title', 'type']:
                    # Gérer les langues qui peuvent être des listes d'objets
                    if key == 'language' and hasattr(value, '__iter__') and not isinstance(value, str):
                         print(f"  - {key}: {', '.join(l.name for l in value)}")
                    elif hasattr(value, 'name'):
                         print(f"  - {key}: {value.name}")
                    else:
                         print(f"  - {key}: {value}")

            # Logique de filtrage
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

        # --- 4. Afficher les résultats finaux filtrés ---
        print("\n" + "="*60)
        print("--- RÉSULTATS APRÈS FILTRAGE ---")
        print(f"Nombre de releases correspondant aux critères : {len(filtered_releases)}")
        print("="*60)

        if filtered_releases:
            print("Titres des releases filtrées :")
            for release in filtered_releases:
                print(f"- {release['title']}")
        else:
            print("Aucune release ne correspond aux critères de filtrage (1080p et langue FRENCH/MULTi).")

    except requests.exceptions.RequestException as e:
        print(f"Erreur lors de la requête vers Prowlarr : {e}")
    except Exception as e:
        print(f"Une erreur inattendue est survenue : {e}")

if __name__ == "__main__":
    main()

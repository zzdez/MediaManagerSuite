# scripts/verify_plex_history.py
# -*- coding: utf-8 -*-

import os
from plexapi.server import PlexServer
from plexapi.exceptions import Unauthorized, NotFound

# --- CONFIGURATION ---
# Remplacez les valeurs ci-dessous par votre URL de serveur Plex et votre token.
# Vous pouvez trouver votre token en suivant ce guide : https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/
PLEX_URL = "http://YOUR_PLEX_URL:32400"  # Ex: "http://192.168.1.10:32400"
PLEX_TOKEN = "YOUR_PLEX_TOKEN"

# --- SCRIPT ---

def main():
    """
    Fonction principale pour se connecter à Plex et vérifier l'historique de visionnage.
    """
    if PLEX_URL == "http://YOUR_PLEX_URL:32400" or PLEX_TOKEN == "YOUR_PLEX_TOKEN":
        print("ERREUR : Veuillez éditer ce script et remplacer les valeurs PLEX_URL et PLEX_TOKEN.")
        return

    print(f"Tentative de connexion au serveur Plex à l'adresse : {PLEX_URL}")

    try:
        plex = PlexServer(PLEX_URL, PLEX_TOKEN)
        print("Connexion au serveur Plex réussie.")
    except Unauthorized:
        print("ERREUR : Token Plex invalide ou expiré. Impossible de s'authentifier.")
        return
    except Exception as e:
        print(f"ERREUR : Une erreur est survenue lors de la connexion au serveur Plex : {e}")
        return

    try:
        # On récupère le compte principal associé au token
        admin_account = plex.myPlexAccount()
        print(f"Connecté en tant que : {admin_account.title} (ID: {admin_account.id})")

        # On récupère l'historique complet pour ce compte
        print("\nRécupération de l'historique de visionnage... (cela peut prendre un moment)")
        history = admin_account.history()
        print(f"Nombre total d'éléments dans l'historique : {len(history)}")

        if not history:
            print("Aucun historique de visionnage trouvé pour ce compte.")
            return

        print("\n--- Analyse de l'historique ---")
        deleted_count = 0
        for item in history:
            try:
                # La méthode source() retourne le média si il existe, sinon None
                media_source = item.source()

                if media_source:
                    # Le média existe toujours
                    media_type = media_source.type.capitalize()
                    title = media_source.title
                    year = f"({media_source.year})" if hasattr(media_source, 'year') else ""
                    print(f"[EXISTANT] {media_type}: {title} {year}")
                else:
                    # Le média a été supprimé
                    # Le titre est souvent conservé dans l'objet 'item' de l'historique
                    deleted_count += 1
                    title = item.title
                    print(f"[SUPPRIMÉ] Média: {title} (Plus de détails non disponibles)")

            except Exception as e:
                print(f"  - Erreur lors de l'analyse d'un élément de l'historique : {e}")

        print("\n--- Fin de l'analyse ---")
        print(f"Nombre total d'éléments supprimés trouvés dans l'historique : {deleted_count}")

    except Exception as e:
        print(f"\nERREUR : Une erreur est survenue lors de la récupération de l'historique : {e}")


if __name__ == "__main__":
    main()

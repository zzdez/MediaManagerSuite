import os
import paramiko
from dotenv import load_dotenv

# Charger les variables d'environnement depuis le fichier .env
load_dotenv()

# --- PARAMÈTRES À CONFIGURER ---
# Remplacez ceci par le chemin complet du fichier que vous voulez supprimer
REMOTE_FILE_TO_DELETE = "/downloads/Termines/radarr_downloads/test_delete.txt"
# --------------------------------

# Lire la configuration depuis les variables d'environnement
SFTP_HOST = os.getenv('SEEDBOX_SFTP_HOST')
SFTP_PORT = int(os.getenv('SEEDBOX_SFTP_PORT', 22))
SFTP_USER = os.getenv('SEEDBOX_SFTP_USER')
SFTP_PASSWORD = os.getenv('SEEDBOX_SFTP_PASSWORD')

print("--- Script de Test de Suppression SFTP ---")
print(f"Hôte: {SFTP_HOST}, Port: {SFTP_PORT}, Utilisateur: {SFTP_USER}")

if not all([SFTP_HOST, SFTP_USER, SFTP_PASSWORD]):
    print("\nERREUR: Configuration SFTP manquante dans le fichier .env. Veuillez vérifier les variables.")
    exit()

transport = None
try:
    # Étape 1: Connexion
    print("\n1. Connexion au serveur SFTP...")
    transport = paramiko.Transport((SFTP_HOST, SFTP_PORT))
    transport.connect(username=SFTP_USER, password=SFTP_PASSWORD)
    sftp = paramiko.SFTPClient.from_transport(transport)
    print("   -> Connexion réussie !")

    # Étape 2: Vérification de l'existence du fichier (stat)
    print(f"\n2. Vérification de l'existence du fichier : {REMOTE_FILE_TO_DELETE}")
    try:
        file_stat = sftp.stat(REMOTE_FILE_TO_DELETE)
        print(f"   -> Fichier trouvé. Taille: {file_stat.st_size} bytes.")
    except FileNotFoundError:
        print("   -> ERREUR: Le fichier n'a pas été trouvé à cet emplacement. Vérifiez le chemin.")
        exit()

    # Étape 3: Tentative de suppression
    print(f"\n3. Tentative de suppression du fichier...")
    sftp.remove(REMOTE_FILE_TO_DELETE)
    print("   -> Commande de suppression envoyée avec succès.")

    # Étape 4: Re-vérification de l'existence du fichier
    print(f"\n4. Re-vérification de l'existence du fichier...")
    try:
        sftp.stat(REMOTE_FILE_TO_DELETE)
        print("   -> ERREUR: Le fichier existe toujours après la suppression !")
    except FileNotFoundError:
        print("   -> SUCCÈS ! Le fichier a été correctement supprimé.")

except Exception as e:
    print(f"\n--- UNE ERREUR EST SURVENUE ---")
    print(f"Type d'erreur: {type(e).__name__}")
    print(f"Message: {e}")

finally:
    if transport:
        transport.close()
        print("\n5. Connexion fermée.")

print("\n--- Fin du script ---")

# app/utils/seedbox_cleaner.py
# -*- coding: utf-8 -*-

import os
import json
import time
from datetime import datetime, timedelta
from flask import current_app

from app.utils import rtorrent_client as rt_client

class SeedboxCleaner:
    """
    Agent intelligent pour le nettoyage automatique de la seedbox.
    """

    def __init__(self, dry_run_override=None):
        """
        Initialise le nettoyeur avec la configuration de l'application.
        """
        self.config = current_app.config
        self.logger = current_app.logger

        # Le mode dry_run peut être forcé (ex: pour un test manuel via l'UI)
        if dry_run_override is not None:
            self.dry_run = dry_run_override
        else:
            self.dry_run = self.config.get('SEEDBOX_CLEANER_DRY_RUN', True)

        self.status_file_path = os.path.join(self.config.get('INSTANCE_FOLDER_PATH'), 'cleanup_status.json')
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "mode": "N/A",
            "dry_run": self.dry_run,
            "space_before": "N/A",
            "space_after": "N/A",
            "deleted_count": 0,
            "deleted_torrents": [],
            "errors": []
        }

    def run(self):
        """
        Exécute le processus de nettoyage complet.
        """
        self.logger.info("--- Début de l'agent de nettoyage de la seedbox ---")
        self.logger.info(f"Mode simulation (Dry Run) : {'Activé' if self.dry_run else 'Désactivé'}")

        # La logique principale sera implémentée ici
        # 1. Vérifier l'espace disque
        used_percent, space_before_str = self._check_disk_space()
        if used_percent is None:
            self.results['errors'].append("Impossible de vérifier l'espace disque. Annulation de l'opération.")
            self.logger.error("Impossible de vérifier l'espace disque. Annulation de l'opération.")
            self._save_status()
            return

        self.results['space_before'] = space_before_str
        self.logger.info(f"Utilisation actuelle de l'espace disque : {used_percent}%")


        # 2. Décider du mode et récupérer les candidats
        emergency_threshold = self.config.get('SEEDBOX_CLEANER_EMERGENCY_THRESHOLD_PERCENT', 90)

        all_torrents, error = rt_client.list_torrents()
        if error:
            self.results['errors'].append("Impossible de récupérer la liste des torrents. Annulation.")
            self.logger.error(f"Impossible de récupérer la liste des torrents: {error}. Annulation.")
            self._save_status()
            return

        if used_percent >= emergency_threshold:
            self.results['mode'] = 'Urgence'
            self.logger.info(f"Seuil d'urgence ({emergency_threshold}%) atteint. Mode d'urgence activé.")

            # Récupérer les candidats et les trier (les plus anciens en premier)
            emergency_candidates = self._get_emergency_candidates(all_torrents)

            # Boucle de suppression jusqu'à ce que l'espace soit suffisant
            while used_percent >= emergency_threshold and emergency_candidates:
                torrent_to_delete = emergency_candidates.pop(0) # Prend le plus ancien
                self.logger.info(f"Mode Urgence: Suppression de '{torrent_to_delete.get('name')}' pour libérer de l'espace.")
                self._delete_torrents([torrent_to_delete]) # Réutiliser la méthode pour un seul torrent

                # Revérifier l'espace disque
                used_percent, space_after_str = self._check_disk_space()
                if used_percent is None:
                    self.logger.error("Impossible de revérifier l'espace disque pendant le mode d'urgence. Arrêt.")
                    self.results['errors'].append("Arrêt d'urgence : impossible de revérifier l'espace disque.")
                    break
                self.logger.info(f"Nouvelle utilisation de l'espace disque : {used_percent}%")
        else:
            self.results['mode'] = 'Routine'
            self.logger.info("Nettoyage de routine activé.")
            torrents_to_delete = self._get_routine_candidates(all_torrents)
            self.logger.info(f"{len(torrents_to_delete)} torrent(s) sélectionné(s) pour suppression.")
            if torrents_to_delete:
                self._delete_torrents(torrents_to_delete)

        # 4. Mettre à jour le statut final
        _, space_after_str = self._check_disk_space()
        self.results['space_after'] = space_after_str
        if space_after_str:
             self.logger.info(f"Espace disque après nettoyage : {space_after_str}")

        self.logger.info("--- Fin de l'agent de nettoyage de la seedbox ---")
        self._save_status()

    def _get_all_torrents(self):
        """Récupère la liste complète des torrents depuis rTorrent."""
        try:
            torrents, error = rt_client.list_torrents()
            if error:
                self.logger.error(f"Erreur lors de la récupération des torrents : {error}")
                return None
            self.logger.info(f"{len(torrents)} torrents trouvés sur la seedbox.")
            return torrents
        except Exception as e:
            self.logger.error(f"Erreur lors de la récupération des torrents : {e}", exc_info=True)
            return None

    def _get_routine_candidates(self, all_torrents):
        """Filtre les torrents pour le nettoyage de routine."""
        min_ratio = self.config.get('SEEDBOX_CLEANER_ROUTINE_MIN_RATIO', 1.0)
        min_seed_days = self.config.get('SEEDBOX_CLEANER_ROUTINE_MIN_SEED_DAYS', 14)
        self.logger.info(f"Critères de routine : Ratio >= {min_ratio}, Durée de seed >= {min_seed_days} jours.")

        candidates = []
        now = datetime.now()
        min_seed_duration = timedelta(days=min_seed_days)

        for torrent in all_torrents:
            try:
                # Le ratio de rtorrent est un entier (ex: 1000 pour 1.0)
                ratio = torrent.get('ratio', 0) / 1000.0
                # d.load_date est un timestamp Unix
                load_date = datetime.fromtimestamp(torrent.get('load_date', 0))
                seeding_time = now - load_date

                if ratio >= min_ratio and seeding_time >= min_seed_duration:
                    candidates.append(torrent)
            except Exception as e:
                self.logger.warning(f"Impossible de traiter le torrent {torrent.get('name', 'N/A')} pour le mode routine : {e}")

        return candidates

    def _get_emergency_candidates(self, all_torrents):
        """Trie les torrents pour le nettoyage d'urgence (les plus anciens d'abord)."""
        self.logger.info("Critères d'urgence : Suppression des torrents les plus anciens en premier.")

        # Trie par 'load_date' (timestamp Unix), du plus petit (plus ancien) au plus grand (plus récent)
        return sorted(all_torrents, key=lambda t: t.get('load_date', 0))

    def _delete_torrents(self, torrents):
        """Supprime une liste de torrents."""
        for torrent in torrents:
            hash = torrent.get('hash')
            name = torrent.get('name')
            if not hash or not name:
                continue

            self.logger.info(f"Tentative de suppression de '{name}' (Hash: {hash})")

            if self.dry_run:
                self.logger.info(f"[SIMULATION] Le torrent '{name}' ne sera pas supprimé.")
                self.results['deleted_count'] += 1
                self.results['deleted_torrents'].append({"name": name, "hash": hash, "status": "simulé"})
                continue

            try:
                # La suppression des données est gérée par la configuration de rtorrent_client
                success, message = rt_client.delete_torrent(hash, delete_data=True)
                if success:
                    self.logger.info(f"Succès de la suppression de '{name}'.")
                    self.results['deleted_count'] += 1
                    self.results['deleted_torrents'].append({"name": name, "hash": hash, "status": "supprimé"})
                else:
                    self.logger.error(f"Échec de la suppression de '{name}': {message}")
                    self.results['errors'].append(f"Échec suppression {name}: {message}")
            except Exception as e:
                self.logger.error(f"Exception lors de la suppression de '{name}': {e}", exc_info=True)
                self.results['errors'].append(f"Exception suppression {name}: {e}")

            # Petite pause pour ne pas surcharger le serveur rTorrent
            time.sleep(1)

    def _format_bytes(self, size_bytes):
        if size_bytes is None:
            return "N/A"
        if size_bytes == 0:
            return "0 B"
        size_name = ("B", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
        i = 0
        while size_bytes >= 1024 and i < len(size_name) - 1:
            size_bytes /= 1024.0
            i += 1
        return f"{size_bytes:.2f} {size_name[i]}"

    def _check_disk_space(self):
        """
        Vérifie l'espace disque en utilisant la fonction fiable de rtorrent_client.
        Retourne le pourcentage d'utilisation (int) et une chaîne formatée (str).
        """
        # Utilise la nouvelle fonction qui appelle get_total_space et get_free_space
        used_bytes, total_bytes, error = rt_client.get_disk_space_info()

        if error:
            self.logger.error(f"Impossible d'obtenir les informations d'espace disque de rTorrent: {error}")
            # L'erreur est déjà loguée dans le client, on la propage ici.
            self.results['errors'].append(f"Erreur d'espace disque: {error}")
            return None, None

        # Gérer le cas où les valeurs sont None (si une erreur non bloquante se produit)
        if used_bytes is None or total_bytes is None:
             self.logger.error("get_disk_space_info a retourné des valeurs None sans erreur explicite.")
             return None, None

        if total_bytes == 0:
            self.logger.warning("L'espace disque total retourné par rTorrent est 0.")
            # Si l'espace utilisé est aussi 0, on considère que c'est 0%. Sinon, c'est une situation anormale (100% ou plus).
            used_percent = 100 if used_bytes > 0 else 0
        else:
            used_percent = int((used_bytes / total_bytes) * 100)

        status_str = f"{self._format_bytes(used_bytes)} / {self._format_bytes(total_bytes)} ({used_percent}%)"

        return used_percent, status_str

    def _save_status(self):
        """
        Sauvegarde les résultats de l'exécution dans le fichier de statut.
        """
        try:
            with open(self.status_file_path, 'w', encoding='utf-8') as f:
                json.dump(self.results, f, indent=4, ensure_ascii=False)
            self.logger.info(f"Résultats du nettoyage sauvegardés dans {self.status_file_path}")
        except Exception as e:
            self.logger.error(f"Erreur lors de la sauvegarde du statut de nettoyage : {e}")

# --- Fonctions utilitaires (si nécessaire) ---

def run_seedbox_cleaner_task():
    """
    Fonction déclenchée par le planificateur de tâches (APScheduler).
    """
    from app import create_app
    app = create_app()
    with app.app_context():
        if not current_app.config.get('SEEDBOX_CLEANER_ENABLED'):
            current_app.logger.info("L'agent de nettoyage de la seedbox est désactivé dans la configuration. Tâche ignorée.")
            return

        cleaner = SeedboxCleaner()
        cleaner.run()

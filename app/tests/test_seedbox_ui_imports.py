import unittest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import os
import shutil

# Supposons que les fonctions à tester sont dans app.seedbox_ui.routes
# Il faudra peut-être ajuster le chemin d'import si ce n'est pas directement importable
# ou si elles sont dans un contexte d'application Flask.
# Pour l'instant, on va essayer d'importer directement.
# Si cela échoue, il faudra une approche avec un contexte d'application Flask.
try:
    from app.seedbox_ui.routes import _execute_mms_sonarr_import, _execute_mms_radarr_import
except ImportError:
    # This is a fallback if the direct import fails, indicating we might need app context
    # For now, we'll proceed assuming direct import might work in a test setup or with adjustments
    _execute_mms_sonarr_import = None
    _execute_mms_radarr_import = None


class TestSeedboxUiImports(unittest.TestCase):

    def setUp(self):
        # Mocks pour les configurations de Flask (current_app.config)
        self.mock_config = {
            'SONARR_URL': 'http://fake-sonarr.com',
            'SONARR_API_KEY': 'fake_sonarr_api_key',
            'RADARR_URL': 'http://fake-radarr.com',
            'RADARR_API_KEY': 'fake_radarr_api_key',
            'LOCAL_STAGING_PATH': '/test/staging',
            'ORPHAN_EXTENSIONS': ['.nfo', '.txt'],
            'AUTO_REMOVE_SUCCESSFUL_FROM_MAP': True
        }

        # Mock pour le logger de Flask
        self.patcher_logger = patch('app.seedbox_ui.routes.current_app.logger', MagicMock())
        self.mock_logger = self.patcher_logger.start()

        # Mock pour current_app.config
        self.patcher_app_config = patch('app.seedbox_ui.routes.current_app.config')
        self.mock_app_config = self.patcher_app_config.start()
        self.mock_app_config.get = lambda key, default=None: self.mock_config.get(key, default)


        # Mocks pour les appels système et les bibliothèques externes
        self.patcher_make_arr_request = patch('app.seedbox_ui.routes._make_arr_request')
        self.mock_make_arr_request = self.patcher_make_arr_request.start()

        self.patcher_shutil_move = patch('shutil.move')
        self.mock_shutil_move = self.patcher_shutil_move.start()

        self.patcher_shutil_copy2 = patch('shutil.copy2') # Pour le fallback de move
        self.mock_shutil_copy2 = self.patcher_shutil_copy2.start()

        self.patcher_os_remove = patch('os.remove') # Pour le fallback de move
        self.mock_os_remove = self.patcher_os_remove.start()

        self.patcher_os_path_exists = patch('os.path.exists')
        self.mock_os_path_exists = self.patcher_os_path_exists.start()

        self.patcher_path_exists = patch('pathlib.Path.exists')
        self.mock_path_exists = self.patcher_path_exists.start()

        self.patcher_path_is_file = patch('pathlib.Path.is_file')
        self.mock_path_is_file = self.patcher_path_is_file.start()

        self.patcher_path_is_dir = patch('pathlib.Path.is_dir')
        self.mock_path_is_dir = self.patcher_path_is_dir.start()

        self.patcher_path_mkdir = patch('pathlib.Path.mkdir')
        self.mock_path_mkdir = self.patcher_path_mkdir.start()

        self.patcher_os_walk = patch('os.walk')
        self.mock_os_walk = self.patcher_os_walk.start()

        self.patcher_torrent_map_manager_update = patch('app.seedbox_ui.routes.torrent_map_manager.update_torrent_status_in_map')
        self.mock_torrent_map_manager_update = self.patcher_torrent_map_manager_update.start()

        self.patcher_torrent_map_manager_remove = patch('app.seedbox_ui.routes.torrent_map_manager.remove_torrent_from_map')
        self.mock_torrent_map_manager_remove = self.patcher_torrent_map_manager_remove.start()

        self.patcher_cleanup_staging = patch('app.seedbox_ui.routes.cleanup_staging_subfolder_recursively')
        self.mock_cleanup_staging = self.patcher_cleanup_staging.start()

        # S'assurer que les fonctions sont disponibles (elles le seront si l'import initial a réussi)
        if _execute_mms_sonarr_import is None or _execute_mms_radarr_import is None:
            # Essayer de charger dans un contexte d'application si l'import direct a échoué
            # Cela suppose une structure d'application Flask typique.
            from flask import Flask
            app = Flask(__name__)
            app.config.update(self.mock_config)
            with app.app_context():
                # Réimporter ou assigner les fonctions ici si elles dépendent du contexte de l'application
                # Ceci est un placeholder, la manière exacte dépend de la structure de votre application.
                # Pour cet exemple, on assume que les fonctions sont globalement accessibles après l'import initial.
                global _execute_mms_sonarr_import, _execute_mms_radarr_import
                from app.seedbox_ui.routes import _execute_mms_sonarr_import as routes_sonarr_import
                from app.seedbox_ui.routes import _execute_mms_radarr_import as routes_radarr_import
                _execute_mms_sonarr_import = routes_sonarr_import
                _execute_mms_radarr_import = routes_radarr_import
            if _execute_mms_sonarr_import is None: # Toujours pas chargé
                 self.fail("Les fonctions _execute_mms_sonarr_import/_execute_mms_radarr_import n'ont pas pu être importées pour le test.")


    def tearDown(self):
        self.patcher_logger.stop()
        self.patcher_app_config.stop()
        self.patcher_make_arr_request.stop()
        self.patcher_shutil_move.stop()
        self.patcher_shutil_copy2.stop()
        self.patcher_os_remove.stop()
        self.patcher_os_path_exists.stop()
        self.patcher_path_exists.stop()
        self.patcher_path_is_file.stop()
        self.patcher_path_is_dir.stop()
        self.patcher_path_mkdir.stop()
        self.patcher_os_walk.stop()
        self.patcher_torrent_map_manager_update.stop()
        self.patcher_torrent_map_manager_remove.stop()
        self.patcher_cleanup_staging.stop()

    # --- Tests pour _execute_mms_sonarr_import ---

    def test_sonarr_import_success_single_file(self):
        # Configurer les mocks pour un cas de succès
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True # L'item dans le staging est un fichier
        self.mock_path_is_dir.return_value = False
        self.mock_make_arr_request.side_effect = [
            ({'path': '/series/The Show', 'title': 'The Show'}, None), # Call for series details
            (True, None) # Call for RescanSeries
        ]
        self.mock_os_walk.return_value = [] # Pas besoin si c'est un fichier

        result = _execute_mms_sonarr_import(
            item_name_in_staging="The.Show.S01E01.mkv",
            series_id_target=1,
            original_release_folder_name_in_staging="The.Show.S01E01.mkv", # Même nom car c'est un fichier
            user_forced_season=1
        )

        self.assertTrue(result['success'])
        self.assertIn("déplacé(s) par MMS", result['message'])
        self.assertIn("Rescan Sonarr initié", result['message'])
        self.mock_shutil_move.assert_called_once()
        # Vérifier que mkdir a été appelé pour le dossier de saison
        self.mock_path_mkdir.assert_called_with(parents=True, exist_ok=True)
        # Vérifier l'appel à cleanup
        self.mock_cleanup_staging.assert_called_once_with(
            str(Path(self.mock_config['LOCAL_STAGING_PATH']) / "The.Show.S01E01.mkv"), # C'est le dossier parent qui est nettoyé si l'item est un fichier
            self.mock_config['LOCAL_STAGING_PATH'],
            self.mock_config['ORPHAN_EXTENSIONS']
        )

    def test_sonarr_import_success_folder_with_one_video(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = False # L'item dans le staging est un dossier
        self.mock_path_is_dir.return_value = True
        self.mock_os_walk.return_value = [
            ('/test/staging/The.Show.S01.Release', [], ['The.Show.S01E01.episode.mkv', 'info.nfo'])
        ]
        # Simuler que Path('/test/staging/The.Show.S01.Release/The.Show.S01E01.episode.mkv').is_file() est vrai
        # Ceci est plus complexe à moquer directement avec le patch global de Path.is_file
        # On va supposer que la logique interne de os.walk et le filtrage par extension fonctionne.

        self.mock_make_arr_request.side_effect = [
            ({'path': '/series/The Show', 'title': 'The Show'}, None),
            (True, None)
        ]

        result = _execute_mms_sonarr_import(
            item_name_in_staging="The.Show.S01.Release", # Nom du dossier dans le staging
            series_id_target=1,
            original_release_folder_name_in_staging="The.Show.S01.Release",
            user_forced_season=1
        )
        self.assertTrue(result['success'])
        self.assertIn("The.Show.S01E01.episode.mkv", result['message'])
        self.mock_shutil_move.assert_called_once()
        self.mock_path_mkdir.assert_called_with(parents=True, exist_ok=True) # Pour le dossier de saison
        self.mock_cleanup_staging.assert_called_once_with(
            str(Path(self.mock_config['LOCAL_STAGING_PATH']) / "The.Show.S01.Release"),
            self.mock_config['LOCAL_STAGING_PATH'],
            self.mock_config['ORPHAN_EXTENSIONS']
        )

    def test_sonarr_import_item_not_in_staging(self):
        self.mock_path_exists.return_value = False # L'item n'existe pas

        result = _execute_mms_sonarr_import("NonExistent.mkv", 1, "NonExistent.mkv", 1)
        self.assertFalse(result['success'])
        self.assertIn("non trouvé", result['message'])

    def test_sonarr_import_api_series_details_fails(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            (None, "API Error 500") # Echec de la récupération des détails de la série
        ]
        result = _execute_mms_sonarr_import("AMedia.S01E01.mkv", 1, "AMedia.S01E01.mkv", 1)
        self.assertFalse(result['success'])
        self.assertIn("Impossible de récupérer détails série", result['message'])

    def test_sonarr_import_no_root_folder_path_in_series_details(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'title': 'The Show'}, None), # Pas de 'path'
        ]
        result = _execute_mms_sonarr_import("AMedia.S01E01.mkv", 1, "AMedia.S01E01.mkv", 1)
        self.assertFalse(result['success'])
        self.assertIn("Chemin racine pour série", result['message'])
        self.assertIn("non trouvé dans Sonarr", result['message'])

    def test_sonarr_import_no_video_file_in_staged_folder(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_dir.return_value = True
        self.mock_os_walk.return_value = [ # Simule un dossier avec seulement un nfo
            ('/test/staging/A.Folder.No.Video', [], ['info.nfo', 'sample.jpg'])
        ]
        result = _execute_mms_sonarr_import("A.Folder.No.Video", 1, "A.Folder.No.Video", 1)
        self.assertFalse(result['success'])
        self.assertIn("Aucun fichier vidéo trouvé", result['message'])

    def test_sonarr_import_move_fails_then_copy_fails(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'path': '/series/The Show', 'title': 'The Show'}, None),
            (True, None) # Rescan
        ]
        self.mock_shutil_move.side_effect = shutil.Error("Move failed")
        self.mock_shutil_copy2.side_effect = shutil.Error("Copy failed")

        result = _execute_mms_sonarr_import("AMedia.S01E01.mkv", 1, "AMedia.S01E01.mkv", 1)
        self.assertFalse(result['success'])
        self.assertIn("Échec copie/suppression", result['message'])
        self.mock_shutil_move.assert_called_once()
        self.mock_shutil_copy2.assert_called_once()
        self.mock_os_remove.assert_not_called() # Car copy2 a échoué

    def test_sonarr_import_rescan_fails(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'path': '/series/The Show', 'title': 'The Show'}, None),
            (None, "Rescan API Error") # Echec du Rescan
        ]
        result = _execute_mms_sonarr_import("AMedia.S01E01.mkv", 1, "AMedia.S01E01.mkv", 1)
        self.assertTrue(result['success']) # L'import est un succès, mais le message doit indiquer l'échec du rescan
        self.assertIn("Échec du Rescan Sonarr", result['message'])

    # --- Tests pour _execute_mms_radarr_import ---

    def test_radarr_import_success_single_file(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'path': '/movies/The Movie (2023)', 'title': 'The Movie'}, None), # Movie details
            (True, None) # RescanMovie
        ]
        result = _execute_mms_radarr_import(
            item_name_in_staging="The.Movie.2023.mkv",
            movie_id_target=10,
            original_release_folder_name_in_staging="The.Movie.2023.mkv"
        )
        self.assertTrue(result['success'])
        self.assertIn("déplacé par MMS", result['message'])
        self.assertIn("Rescan Radarr initié", result['message'])
        self.mock_shutil_move.assert_called_once()
        self.mock_path_mkdir.assert_called_with(parents=True, exist_ok=True) # Pour le dossier du film
        self.mock_cleanup_staging.assert_called_once()

    def test_radarr_import_success_folder_with_one_video(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_dir.return_value = True
        self.mock_path_is_file.return_value = False # l'item de staging est un dossier
        self.mock_os_walk.return_value = [
            ('/test/staging/The.Movie.2023.Release', [], ['movie.title.2023.mkv', 'info.nfo'])
        ]
        self.mock_make_arr_request.side_effect = [
            ({'path': '/movies/The Movie (2023)', 'title': 'The Movie'}, None),
            (True, None)
        ]
        result = _execute_mms_radarr_import(
            "The.Movie.2023.Release", 10, "The.Movie.2023.Release"
        )
        self.assertTrue(result['success'])
        self.assertIn("movie.title.2023.mkv", self.mock_shutil_move.call_args[0][1]) # Vérifie que le bon fichier est déplacé
        self.mock_cleanup_staging.assert_called_once()

    def test_radarr_import_item_not_in_staging(self):
        self.mock_path_exists.return_value = False
        result = _execute_mms_radarr_import("NonExistent.mkv", 10, "NonExistent.mkv")
        self.assertFalse(result['success'])
        self.assertIn("non trouvé", result['message'])

    def test_radarr_import_api_movie_details_fails(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            (None, "API Error 500") # Echec des détails du film
        ]
        result = _execute_mms_radarr_import("AMovie.mkv", 10, "AMovie.mkv")
        self.assertFalse(result['success'])
        self.assertIn("Erreur détails film Radarr ID", result['message'])

    def test_radarr_import_no_movie_path_in_details(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'title': 'The Movie'}, None), # Pas de 'path'
        ]
        result = _execute_mms_radarr_import("AMovie.mkv", 10, "AMovie.mkv")
        self.assertFalse(result['success'])
        self.assertIn("Chemin ('path') manquant pour film ID", result['message'])

    def test_radarr_import_no_video_file_in_staged_item(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_dir.return_value = True # C'est un dossier
        self.mock_os_walk.return_value = [ # Simule un dossier avec seulement un nfo
            ('/test/staging/A.Movie.Folder.No.Video', [], ['info.nfo'])
        ]
        result = _execute_mms_radarr_import("A.Movie.Folder.No.Video", 10, "A.Movie.Folder.No.Video")
        self.assertFalse(result['success'])
        self.assertIn("Aucun fichier vidéo trouvé", result['message'])

    def test_radarr_import_move_fails_then_copy_fails(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'path': '/movies/The Movie (2023)', 'title': 'The Movie'}, None),
            (True, None) # Rescan
        ]
        self.mock_shutil_move.side_effect = shutil.Error("Move failed")
        self.mock_shutil_copy2.side_effect = shutil.Error("Copy failed")

        result = _execute_mms_radarr_import("AMovie.mkv", 10, "AMovie.mkv")
        self.assertFalse(result['success'])
        self.assertIn("Échec du déplacement (copie/suppression)", result['message'])

    def test_radarr_import_rescan_fails(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'path': '/movies/The Movie (2023)', 'title': 'The Movie'}, None),
            (None, "Rescan API Error") # Echec du Rescan
        ]
        result = _execute_mms_radarr_import("AMovie.mkv", 10, "AMovie.mkv")
        self.assertTrue(result['success'])
        self.assertIn("Échec du Rescan Radarr", result['message'])

if __name__ == '__main__':
    unittest.main()

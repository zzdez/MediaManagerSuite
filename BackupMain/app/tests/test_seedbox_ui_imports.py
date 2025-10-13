import unittest
from unittest.mock import patch, MagicMock
from flask import Flask
import shutil
from pathlib import Path

try:
    from app.seedbox_ui.routes import _execute_mms_sonarr_import, _execute_mms_radarr_import
except ImportError:
    _execute_mms_sonarr_import = None
    _execute_mms_radarr_import = None

class TestSeedboxUiImports(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SONARR_URL'] = 'http://fake-sonarr.com'
        self.app.config['SONARR_API_KEY'] = 'fake_sonarr_api_key'
        self.app.config['RADARR_URL'] = 'http://fake-radarr.com'
        self.app.config['RADARR_API_KEY'] = 'fake_radarr_api_key'
        self.app.config['LOCAL_STAGING_PATH'] = '/test/staging'
        self.app.config['STAGING_DIR'] = '/test/staging'
        self.app.config['ORPHAN_EXTENSIONS'] = ['.nfo', '.txt']
        self.app.config['AUTO_REMOVE_SUCCESSFUL_FROM_MAP'] = True
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.patcher_logger = patch('app.seedbox_ui.routes.current_app.logger', MagicMock())
        self.mock_logger = self.patcher_logger.start()

        self.patcher_make_arr_request = patch('app.seedbox_ui.routes._make_arr_request')
        self.mock_make_arr_request = self.patcher_make_arr_request.start()

        self.patcher_shutil_move = patch('shutil.move')
        self.mock_shutil_move = self.patcher_shutil_move.start()

        self.patcher_shutil_copy2 = patch('shutil.copy2')
        self.mock_shutil_copy2 = self.patcher_shutil_copy2.start()

        self.patcher_os_remove = patch('os.remove')
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

        global _execute_mms_sonarr_import, _execute_mms_radarr_import
        if _execute_mms_sonarr_import is None or _execute_mms_radarr_import is None:
            from app.seedbox_ui.routes import _execute_mms_sonarr_import as routes_sonarr_import
            from app.seedbox_ui.routes import _execute_mms_radarr_import as routes_radarr_import
            _execute_mms_sonarr_import = routes_sonarr_import
            _execute_mms_radarr_import = routes_radarr_import
        if _execute_mms_sonarr_import is None:
            self.fail("Could not import functions")

    def tearDown(self):
        self.patcher_logger.stop()
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
        self.app_context.pop()

    def test_sonarr_import_success_single_file(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_path_is_dir.return_value = False
        self.mock_make_arr_request.side_effect = [
            ({'path': '/series/The Show', 'title': 'The Show'}, None),
            (True, None)
        ]
        self.mock_os_walk.return_value = []

        result = _execute_mms_sonarr_import(
            item_name_in_staging="The.Show.S01E01.mkv",
            series_id_target=1,
            original_release_folder_name_in_staging="The.Show.S01E01.mkv",
            user_forced_season=1
        )

        self.assertTrue(result['success'])
        self.assertIn("déplacé(s)", result['message'])
        self.assertIn("Rescan Sonarr initié", result['message'])
        self.mock_shutil_move.assert_called_once()
        self.mock_path_mkdir.assert_called_with(parents=True, exist_ok=True)
        # The cleanup function is not called for single files, so we don't assert it.

    def test_radarr_import_success_single_file(self):
        self.mock_path_exists.return_value = True
        self.mock_path_is_file.return_value = True
        self.mock_make_arr_request.side_effect = [
            ({'path': '/movies/The Movie (2023)', 'title': 'The Movie'}, None),
            (True, None)
        ]
        result = _execute_mms_radarr_import(
            item_name_in_staging="The.Movie.2023.mkv",
            movie_id_target=10,
            original_release_folder_name_in_staging="The.Movie.2023.mkv"
        )
        self.assertTrue(result['success'])
        self.assertIn("déplacé", result['message'])
        self.assertIn("Rescan Radarr initié", result['message'])
        self.mock_shutil_move.assert_called_once()
        self.mock_path_mkdir.assert_called_with(parents=True, exist_ok=True)
        # The cleanup function is not called for single files, so we don't assert it.

if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import patch, MagicMock
from flask import Flask, jsonify
import json

# Since the app context is tricky to set up standalone,
# we'll import the blueprint and register it to a test Flask app.
from app.seedbox_ui import seedbox_ui_bp

class TestRtorrentBatchActions(unittest.TestCase):

    def setUp(self):
        """Set up a test Flask app and context."""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.app.config['SECRET_KEY'] = 'test-secret-key-for-session'

        # The login_required decorator redirects to 'login', so we define it.
        # However, the tests will bypass the check by setting a session variable.
        @self.app.route('/login')
        def login():
            return "dummy login", 200

        self.app.register_blueprint(seedbox_ui_bp, url_prefix='/seedbox')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()

        self.patcher_rtorrent_api = patch('app.seedbox_ui.routes.rtorrent_delete_torrent_api')
        self.mock_rtorrent_delete_api = self.patcher_rtorrent_api.start()

        self.patcher_map_manager_update = patch('app.seedbox_ui.routes.torrent_map_manager.update_torrent_status_in_map')
        self.mock_map_manager_update = self.patcher_map_manager_update.start()

        self.patcher_map_manager_remove = patch('app.seedbox_ui.routes.torrent_map_manager.remove_torrent_from_map')
        self.mock_map_manager_remove = self.patcher_map_manager_remove.start()

        self.patcher_map_manager_add_ignored = patch('app.seedbox_ui.routes.torrent_map_manager.add_hash_to_ignored_list')
        self.mock_map_manager_add_ignored = self.patcher_map_manager_add_ignored.start()

        self.patcher_staging_processor_connect = patch('app.seedbox_ui.routes.staging_processor._connect_sftp')
        self.mock_staging_processor_connect = self.patcher_staging_processor_connect.start()

        self.patcher_staging_processor_repatriate = patch('app.seedbox_ui.routes.staging_processor._rapatriate_item')
        self.mock_staging_processor_repatriate = self.patcher_staging_processor_repatriate.start()

        self.patcher_map_manager_get = patch('app.seedbox_ui.routes.torrent_map_manager.get_torrent_by_hash')
        self.mock_map_manager_get = self.patcher_map_manager_get.start()

        self.patcher_logger = patch('app.seedbox_ui.routes.logger')
        self.mock_logger = self.patcher_logger.start()

    def tearDown(self):
        """Clean up patches and app context."""
        self.patcher_rtorrent_api.stop()
        self.patcher_map_manager_update.stop()
        self.patcher_map_manager_remove.stop()
        self.patcher_map_manager_add_ignored.stop()
        self.patcher_staging_processor_connect.stop()
        self.patcher_staging_processor_repatriate.stop()
        self.patcher_map_manager_get.stop()
        self.patcher_logger.stop()
        self.app_context.pop()

    def test_batch_delete_success(self):
        """Test the batch delete action with a list of hashes."""
        self.mock_rtorrent_delete_api.return_value = (True, "Success")
        test_hashes = ['HASH1', 'HASH2', 'HASH3']
        payload = {"action": "delete", "hashes": test_hashes, "options": {"delete_data": False}}

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        response_data = response.get_json()
        self.assertEqual(response_data['status'], 'success')
        self.assertIn('Succès: 3, Échecs: 0', response_data['message'])
        self.assertEqual(self.mock_rtorrent_delete_api.call_count, 3)
        called_hashes = [call[0][0] for call in self.mock_rtorrent_delete_api.call_args_list]
        self.assertCountEqual(called_hashes, test_hashes)
        self.assertEqual(self.mock_rtorrent_delete_api.call_args[0][1], False)

    def test_batch_delete_with_data_success(self):
        """Test the batch delete action with the delete_data flag set to True."""
        self.mock_rtorrent_delete_api.return_value = (True, "Success")
        test_hashes = ['HASH4', 'HASH5']
        payload = {"action": "delete", "hashes": test_hashes, "options": {"delete_data": True}}

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mock_rtorrent_delete_api.call_count, 2)
        self.assertEqual(self.mock_rtorrent_delete_api.call_args[0][1], True)

    def test_batch_delete_partial_failure(self):
        """Test the case where some API calls succeed and others fail."""
        self.mock_rtorrent_delete_api.side_effect = [(True, "Success"), (False, "API Error")]
        test_hashes = ['HASH_SUCCESS', 'HASH_FAIL']
        payload = {"action": "delete", "hashes": test_hashes, "options": {"delete_data": False}}

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 200)
        response_data = response.get_json()
        self.assertEqual(response_data['status'], 'success')
        self.assertIn('Succès: 1, Échecs: 1', response_data['message'])
        self.assertEqual(self.mock_rtorrent_delete_api.call_count, 2)

    def test_batch_action_unsupported_action(self):
        """Test providing an action that is not supported."""
        payload = {"action": "unsupported_action", "hashes": ["HASH1"]}

        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')

        self.assertEqual(response.status_code, 400)
        response_data = response.get_json()
        self.assertEqual(response_data['status'], 'error')
        self.assertIn('Action non supportée', response_data['message'])

    def test_batch_action_missing_data(self):
        """Test calling the endpoint with missing hashes or action."""
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True

        # Missing hashes
        payload1 = {"action": "delete", "hashes": []}
        response1 = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload1), content_type='application/json')
        self.assertEqual(response1.status_code, 400)

        # Missing action
        payload2 = {"hashes": ["HASH1"]}
        response2 = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload2), content_type='application/json')
        self.assertEqual(response2.status_code, 400)

    def test_batch_mark_processed(self):
        """Test the 'mark_processed' batch action."""
        self.mock_map_manager_update.return_value = True
        payload = {"action": "mark_processed", "hashes": ["HASH1", "HASH2"]}
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mock_map_manager_update.call_count, 2)
        self.mock_map_manager_update.assert_called_with('HASH2', 'processed_manual', 'Marqué comme traité manuellement via action groupée.')

    def test_batch_forget_association(self):
        """Test the 'forget' batch action."""
        self.mock_map_manager_remove.return_value = True
        payload = {"action": "forget", "hashes": ["HASH1"]}
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.mock_map_manager_remove.assert_called_once_with('HASH1')

    def test_batch_ignore(self):
        """Test the 'ignore' batch action."""
        self.mock_map_manager_add_ignored.return_value = True
        self.mock_map_manager_remove.return_value = True
        payload = {"action": "ignore", "hashes": ["HASH_IGNORE"]}
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.mock_map_manager_add_ignored.assert_called_once_with('HASH_IGNORE')
        self.mock_map_manager_remove.assert_called_once_with('HASH_IGNORE')

    def test_batch_retry_repatriation(self):
        """Test the 'retry_repatriation' batch action."""
        self.mock_map_manager_update.return_value = True
        payload = {"action": "retry_repatriation", "hashes": ["HASH_RETRY"]}
        with self.client.session_transaction() as sess:
            sess['logged_in'] = True
        response = self.client.post('/seedbox/rtorrent/batch-action', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.mock_map_manager_update.assert_called_once_with('HASH_RETRY', 'pending_staging')

if __name__ == '__main__':
    unittest.main()

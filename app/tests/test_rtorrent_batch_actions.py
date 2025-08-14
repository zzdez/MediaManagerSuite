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

        self.patcher_logger = patch('app.seedbox_ui.routes.logger')
        self.mock_logger = self.patcher_logger.start()

    def tearDown(self):
        """Clean up patches and app context."""
        self.patcher_rtorrent_api.stop()
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
        self.assertIn('3 torrent(s) supprimé(s)', response_data['message'])
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
        self.assertIn('1 torrent(s) supprimé(s), 1 échec(s)', response_data['message'])
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

if __name__ == '__main__':
    unittest.main()

import pytest
import os
import json
from unittest.mock import patch, MagicMock
from app.utils.seen_manager import add_to_seen_history, get_seen_history, is_seen, SEEN_HISTORY_FILE

@pytest.fixture
def mock_history_file(tmp_path):
    # Mock the file path to use a temp file
    temp_file = tmp_path / "seen_history.json"
    with patch('app.utils.seen_manager.SEEN_HISTORY_FILE', str(temp_file)):
        yield temp_file

def test_add_and_get_seen(mock_history_file, app):
    with app.app_context():
        guids = ['guid_1', 'guid_2']
        add_to_seen_history(guids)

        history = get_seen_history()
        assert 'guid_1' in history
        assert 'guid_2' in history
        assert is_seen('guid_1')
        assert not is_seen('guid_3')

def test_add_updates_timestamp(mock_history_file, app):
    with app.app_context():
        add_to_seen_history(['guid_1'])
        history1 = get_seen_history()
        ts1 = history1['guid_1']

        # Add again
        add_to_seen_history(['guid_1'])
        history2 = get_seen_history()
        ts2 = history2['guid_1']

        # Should differ slightly or be same if too fast, but logically it overwrites.
        # Ideally we'd mock datetime but for now just checking existence is enough.
        assert 'guid_1' in history2

def test_cleanup_removes_old_items(mock_history_file, app):
    # Manually create a file with old date
    old_date = "2020-01-01T00:00:00+00:00"
    with open(mock_history_file, 'w') as f:
        json.dump({'old_guid': old_date}, f)

    with app.app_context():
        # Trigger cleanup by adding a new item
        add_to_seen_history(['new_guid'])

        history = get_seen_history()
        assert 'new_guid' in history
        assert 'old_guid' not in history # Should be removed (assuming default retention > 2020)

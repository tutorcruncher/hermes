"""
Tests for Pipedrive API v2 helper functions.
"""

from app.pipedrive import api


class TestPipedriveAPIHelpers:
    """Test Pipedrive API helper functions"""

    def test_get_changed_fields_returns_only_changed(self):
        """Test that get_changed_fields only returns fields that changed"""
        old_data = {'name': 'Test', 'value': 10, 'unchanged': 'same'}
        new_data = {'name': 'Updated', 'value': 10, 'unchanged': 'same', 'new_field': 'new'}

        changed = api.get_changed_fields(old_data, new_data)

        assert changed == {'name': 'Updated', 'new_field': 'new'}

    def test_get_changed_fields_with_none_old_data(self):
        """Test that get_changed_fields returns all fields when old_data is None"""
        new_data = {'name': 'Test', 'value': 10}

        changed = api.get_changed_fields(None, new_data)

        assert changed == new_data

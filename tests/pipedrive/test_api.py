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

    def test_get_changed_fields_ignores_custom_fields_and_address_subfields_hermes_does_not_send(self):
        """Pipedrive returns every custom field and address subfield, and only the ones Hermes sends are compared"""
        old_data = {
            'custom_fields': {'aaa': 'payg', 'bbb': None, 'ccc': 'Australia'},
            'address': {'value': 'GB', 'country': 'GB', 'route': None, 'formatted_address': None},
        }
        new_data = {'custom_fields': {'aaa': 'payg'}, 'address': {'value': 'GB', 'country': 'GB'}}

        assert api.get_changed_fields(old_data, new_data) == {}

    def test_get_changed_fields_unwraps_pipedrive_custom_field_values(self):
        """Custom field values wrapped as {'type', 'value'} or {'id', 'type'} compare by the value inside"""
        old_data = {
            'custom_fields': {
                'aaa': {'type': 'varchar', 'value': '3163'},
                'bbb': {'type': 'double', 'value': 4},
                'ccc': {'id': 506, 'type': 'enum'},
            }
        }
        new_data = {'custom_fields': {'aaa': '3163', 'bbb': 4, 'ccc': 506}}

        assert api.get_changed_fields(old_data, new_data) == {}

    def test_get_changed_fields_sends_whole_custom_fields_and_address_when_one_subfield_changed(self):
        """A changed subfield sends all the subfields Hermes has, as Pipedrive needs the address value with its
        country"""
        old_data = {
            'custom_fields': {'aaa': {'type': 'varchar', 'value': 'payg'}, 'bbb': {'type': 'varchar', 'value': '5'}},
            'address': {'value': 'GB', 'country': 'GB', 'route': None},
        }
        new_data = {'custom_fields': {'aaa': 'startup', 'bbb': '5'}, 'address': {'value': 'US', 'country': 'US'}}

        assert api.get_changed_fields(old_data, new_data) == new_data

    def test_get_changed_fields_sends_custom_field_pipedrive_does_not_have(self):
        """A custom field Pipedrive has no value for, or custom_fields Pipedrive did not return, is changed"""
        new_data = {'custom_fields': {'aaa': 'payg'}}

        assert api.get_changed_fields({'custom_fields': {'aaa': None}}, new_data) == new_data
        assert api.get_changed_fields({'custom_fields': {}}, new_data) == new_data
        assert api.get_changed_fields({}, new_data) == new_data

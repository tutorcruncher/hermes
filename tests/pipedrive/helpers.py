"""Shared utilities for Pipedrive tests."""

import re
from urllib.parse import parse_qs

from httpx import HTTPError


class FakePipedrive:
    def __init__(self):
        self.db = {'organizations': {}, 'persons': {}, 'deals': {}, 'activities': {}}


class MockResponse:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self.json_data = json_data

    def json(self):
        return self.json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(f'{self.status_code} {self.json_data["error"]}')


def fake_pd_request(fake_pipedrive: FakePipedrive):
    def _pd_request(*, url: str, method: str, data: dict):
        obj_type = re.search(r'/api/v1/(.*?)(?:/|\?api_token=)', url).group(1)
        extra_path = re.search(rf'/api/v1/{obj_type}/(.*?)(?=\?)', url)
        extra_path = extra_path and extra_path.group(1)
        obj_id = re.search(rf'/api/v1/{obj_type}/(\d+)', url)
        obj_id = obj_id and int(obj_id.group(1))
        if method == 'GET':
            if obj_id:
                # Return 404 if object doesn't exist in the fake database
                if obj_id not in fake_pipedrive.db[obj_type]:
                    return MockResponse(404, {'error': 'Not Found'})
                return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
            else:
                # if object type includes /search then it's a search request
                if 'search' in extra_path:
                    search_term = parse_qs(re.search(r'\?(.*)', url).group(1))['term'][0]
                    objs = [
                        obj
                        for obj in fake_pipedrive.db[obj_type].values()
                        if any(search_term in str(v) for v in obj.values())
                    ]
                    return MockResponse(200, {'data': {'items': [{'item': i} for i in objs]}})
                else:
                    return MockResponse(200, {'data': list(fake_pipedrive.db[obj_type].values())})
        elif method == 'POST':
            obj_id = len(fake_pipedrive.db[obj_type].keys()) + 1
            data['id'] = obj_id
            fake_pipedrive.db[obj_type][obj_id] = data
            return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
        elif method == 'PUT':
            if obj_id not in fake_pipedrive.db[obj_type]:
                return MockResponse(404, {'error': 'Not Found'})
            fake_pipedrive.db[obj_type][obj_id].update(**data)
            return MockResponse(200, {'data': fake_pipedrive.db[obj_type][obj_id]})
        else:
            assert method == 'DELETE'
            if obj_id not in fake_pipedrive.db[obj_type]:
                return MockResponse(404, {'error': 'Not Found'})
            del fake_pipedrive.db[obj_type][obj_id]
            return MockResponse(200, {'data': {'id': obj_id}})

    return _pd_request


def basic_pd_org_data():
    return {
        'meta': {'action': 'change', 'entity': 'organization', 'version': '2.0'},
        'data': {'owner_id': 10, 'id': 20, 'name': 'Test company', 'address_country': None},
        'previous': None,
    }


def basic_pd_person_data():
    return {
        'meta': {'action': 'change', 'entity': 'person', 'version': '2.0'},
        'data': {
            'owner_id': 10,
            'id': 30,
            'name': 'Brian Blessed',
            'email': [''],
            'phone': [{'value': '0208112555', 'primary': 'true'}],
            'org_id': 20,
        },
        'previous': {},
    }


def basic_pd_deal_data():
    return {
        'meta': {'action': 'change', 'entity': 'deal', 'version': '2.0'},
        'data': {
            'id': 40,
            'person_id': 30,
            'stage_id': 50,
            'close_time': None,
            'org_id': 20,
            'status': 'open',
            'title': 'Deal 1',
            'pipeline_id': 60,
            'user_id': 10,
        },
        'previous': None,
    }


def basic_pd_pipeline_data():
    return {
        'meta': {'action': 'change', 'entity': 'pipeline', 'version': '2.0'},
        'data': {'name': 'Pipeline 1', 'id': 60, 'active': True},
        'previous': {},
    }


def basic_pd_stage_data():
    return {
        'meta': {'action': 'change', 'entity': 'stage', 'version': '2.0'},
        'data': {'name': 'Stage 1', 'pipeline_id': 60, 'id': 50},
        'previous': {},
    }

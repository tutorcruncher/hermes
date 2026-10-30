"""Local stand-in for Pipedrive, TC2 and Google Calendar, so /pr-uat runs the real sync paths with nothing real reached.

Pipedrive keeps the objects Hermes creates, so a later GET or PATCH sees them, and answers 404 for anything else.
TC2 serves a client from <dir>/tc2-clients/<id>.json, and 404 when there is no such file. Calendar is always free
unless <dir>/google-busy.json holds a list of {start, end}, and accepts every event.

Every request is appended to service-requests.jsonl in --dir: that file is the evidence of what each service would
have received. POST /_uat/fail with {"path": "<fragment>", "status": 429, "count": 1} makes the next requests whose
path has that fragment fail with that status.
"""

import argparse
import json
import re
from collections import defaultdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dir', required=True, type=Path)
    parser.add_argument('--port', required=True, type=int)
    args = parser.parse_args()

    log_path = args.dir / 'service-requests.jsonl'
    store: dict[str, dict[int, dict]] = defaultdict(dict)
    failures: list[dict] = []
    lock = Lock()
    next_id = [1000]

    def pipedrive(method: str, collection: str, obj_id: int | None, body: dict) -> tuple[int, dict]:
        objects = store[collection]
        if obj_id is None and method == 'POST':
            next_id[0] += 1
            objects[next_id[0]] = {**body, 'id': next_id[0]}
            return 201, {'success': True, 'data': objects[next_id[0]]}
        if obj_id is None and method == 'GET':
            return 200, {'success': True, 'data': list(objects.values())}
        if obj_id not in objects:
            return 404, {'success': False, 'error': 'not found'}
        if method == 'DELETE':
            del objects[obj_id]
            return 200, {'success': True, 'data': {'id': obj_id}}
        if method == 'PATCH':
            custom_fields = {**objects[obj_id].get('custom_fields', {}), **body.get('custom_fields', {})}
            objects[obj_id] = {**objects[obj_id], **body, 'custom_fields': custom_fields}
        return 200, {'success': True, 'data': objects[obj_id]}

    def tc2(path: str) -> tuple[int, dict]:
        match = re.fullmatch(r'/tc2/api/clients/(\d+)/', path)
        client_file = args.dir / 'tc2-clients' / f'{match.group(1)}.json' if match else None
        if client_file and client_file.exists():
            return 200, json.loads(client_file.read_text())
        return 404, {'detail': 'Not found.'}

    def google(path: str, body: dict) -> tuple[int, dict]:
        if path.endswith('/freeBusy'):
            busy_file = args.dir / 'google-busy.json'
            busy = json.loads(busy_file.read_text()) if busy_file.exists() else []
            return 200, {'calendars': {item['id']: {'busy': busy} for item in body.get('items', [])}}
        return 200, {'id': 'uat-event', 'status': 'confirmed'}

    def respond(method: str, path: str, body: dict) -> tuple[int, dict]:
        for failure in failures:
            if failure['path'] in path and failure['count'] > 0:
                failure['count'] -= 1
                return failure['status'], {'success': False, 'error': 'failed by /_uat/fail'}
        pipedrive_path = re.fullmatch(r'/pipedrive/api/v2/([a-z]+)(?:/(\d+))?', path)
        if pipedrive_path:
            collection, obj_id = pipedrive_path.groups()
            return pipedrive(method, collection, int(obj_id) if obj_id else None, body)
        if path.startswith('/tc2/'):
            return tc2(path)
        if path.startswith('/google/'):
            return google(path, body)
        return 404, {'error': f'no fake for {path}'}

    class Handler(BaseHTTPRequestHandler):
        def _serve(self) -> None:
            raw = self.rfile.read(int(self.headers.get('Content-Length') or 0))
            body = json.loads(raw) if raw else {}
            path = self.path.split('?')[0]
            with lock:
                if path == '/_uat/fail':
                    failures.append(body)
                    status, response = 200, {'ok': True}
                else:
                    status, response = respond(self.command, path, body)
                    with log_path.open('a') as f:
                        entry = {'method': self.command, 'path': self.path, 'body': body, 'status': status}
                        f.write(json.dumps(entry) + '\n')
            payload = json.dumps(response).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _serve

        def log_message(self, format: str, *log_args) -> None:
            print(format % log_args, flush=True)

    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()


if __name__ == '__main__':
    main()

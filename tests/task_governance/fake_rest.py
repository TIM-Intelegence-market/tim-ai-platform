"""In-memory GitHub REST server behind the gateway's injectable transport. Records every call."""
import json
import re
from urllib.parse import parse_qs, urlparse


class FakeRest:
    def __init__(self, repository='owner/repo'):
        self.repo = repository
        self.issues, self.comments, self.calls = {}, {}, []
        self.alias = {}                 # asked issue number -> served issue number (models a silent redirect)
        self.fail = {}                  # (method, path-regex) -> status code or Exception instance
        self.next_number = 0
        self.repo_visible = True
        self.lose_create_reply = False   # the issue is created, but the answer never arrives
        self.login = 'owner'             # the account behind the token (GET /user)
        self.lag_listing = False         # new issues are missing from the listing until release_listing(), single reads see them
        self.unlisted = set()

    def seed(self, number, body='', state='open', login='owner', pr=False):
        item = {'number': number, 'state': state, 'title': f'issue {number}', 'body': body, 'user': {'login': login},
                'repository_url': f'https://api.github.com/repos/{self.repo}'}
        if pr:
            item['pull_request'] = {'url': 'x'}
        self.issues[number] = item
        self.comments.setdefault(number, [])

    def release_listing(self):
        self.unlisted.clear()

    def writes(self):
        return [c for c in self.calls if c[0] != 'GET']

    def __call__(self, method, url, headers, body, timeout):
        parsed = urlparse(url)
        path = parsed.path
        self.calls.append((method, path, timeout))
        for (m, pattern), outcome in self.fail.items():
            if m == method and re.search(pattern, path):
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome, b'{"message": "SECRET-DETAIL"}'
        payload = json.loads(body) if body else None
        base = f'/repos/{self.repo}/issues'
        if path == base:
            if method == 'GET':
                query = parse_qs(parsed.query)
                per, page = int(query['per_page'][0]), int(query['page'][0])
                items = [self.issues[n] for n in sorted(self.issues) if n not in self.unlisted]
                return 200, json.dumps(items[(page - 1) * per: page * per]).encode()
            if method == 'POST':
                self.next_number += 1
                number = self.next_number
                self.seed(number, payload['body'])
                self.issues[number]['title'] = payload['title']
                if self.lag_listing:
                    self.unlisted.add(number)
                if self.lose_create_reply:
                    self.fail[('GET', r'/issues$')] = 503     # and GitHub stops answering listings afterwards
                    raise TimeoutError('reply lost')
                return 201, json.dumps(self.issues[number]).encode()
        m = re.fullmatch(re.escape(base) + r'/(\d+)', path)
        if m:
            number = self.alias.get(int(m.group(1)), int(m.group(1))) if method == 'GET' else int(m.group(1))
            if number not in self.issues:
                return 404, b'{}'
            if method == 'GET':
                return 200, json.dumps(self.issues[number]).encode()
            if method == 'PATCH':
                self.issues[number].update(payload)
                return 200, json.dumps(self.issues[number]).encode()
        m = re.fullmatch(re.escape(base) + r'/(\d+)/comments', path)
        if m:
            number = int(m.group(1))
            if method == 'GET':
                query = parse_qs(parsed.query)
                per, page = int(query['per_page'][0]), int(query['page'][0])
                return 200, json.dumps(self.comments.get(number, [])[(page - 1) * per: page * per]).encode()
            if method == 'POST':
                self.comments.setdefault(number, []).append({'body': payload['body']})
                return 201, b'{}'
        if path == '/user' and method == 'GET':
            return 200, json.dumps({'login': self.login}).encode()
        if path == f'/repos/{self.repo}' and method == 'GET':
            return (200, b'{}') if self.repo_visible else (404, b'{}')
        return 400, b'{}'

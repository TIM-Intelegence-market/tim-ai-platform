import re

import pytest

from src.task_governance import (CreateNotSent, EnsureOutcome, GitHubError, GitHubRestGateway, MappingState, TaskRegistry,
                                 TaskRequest, ensure_task, fingerprint_marker)
from src.task_governance.github_gateway import BODY_BEGIN, BODY_END, PAGE_SIZE, _NotSent
from tests.task_governance.fake_rest import FakeRest

TOKEN = 'ghp_SUPERSECRETTOKEN'


def req(**kw):
    base = dict(mission_id='M09', phase_id='P0', task_type='SAMPLE_TASK', target='TIM', schema_version='v1',
                title='Sample', body='the body')
    base.update(kw)
    return TaskRequest(**base)


@pytest.fixture
def rest():
    return FakeRest()


@pytest.fixture
def gw(rest):
    return GitHubRestGateway('owner/repo', TOKEN, transport=rest)


def test_find_issues_matches_marker_and_reports_pull_requests(rest, gw):
    fp = req().fingerprint
    rest.seed(5, fingerprint_marker(fp))
    rest.seed(6, 'unrelated')
    rest.seed(7, 'x ' + fingerprint_marker(fp), pr=True, login='stranger')
    found = gw.find_issues(fp, req().key)
    assert [(i.number, i.is_pull_request, i.author) for i in found] == [(5, False, 'owner'), (7, True, 'stranger')]


def test_find_issues_paginates_and_refuses_to_guess_beyond_the_cap(rest):
    fp = req().fingerprint
    for n in range(1, PAGE_SIZE * 2 + 2):
        rest.seed(n, fingerprint_marker(fp) if n == PAGE_SIZE * 2 + 1 else '')
    assert [i.number for i in GitHubRestGateway('owner/repo', TOKEN, transport=rest).find_issues(fp, '')] == [PAGE_SIZE * 2 + 1]
    with pytest.raises(GitHubError):
        GitHubRestGateway('owner/repo', TOKEN, transport=rest, max_pages=2).find_issues(fp, '')


def test_get_issue_none_only_for_confirmed_404(rest, gw):
    rest.seed(9)
    assert gw.get_issue(9).number == 9
    assert gw.get_issue(10) is None
    for status in (403, 429, 500, 502):
        rest.fail[('GET', r'/issues/9$')] = status
        with pytest.raises(GitHubError):
            gw.get_issue(9)


def test_errors_never_carry_token_or_response_body(rest, gw):
    rest.fail[('GET', r'/issues$')] = 403
    with pytest.raises(GitHubError) as exc:
        gw.find_issues('x', 'y')
    assert TOKEN not in str(exc.value) and 'SECRET-DETAIL' not in str(exc.value) and TOKEN not in repr(gw)


def test_bad_json_and_missing_number_raise(rest, gw):
    bad = GitHubRestGateway('owner/repo', TOKEN, transport=lambda *a: (200, b'<html>'))
    with pytest.raises(GitHubError):
        bad.get_issue(1)
    odd = GitHubRestGateway('owner/repo', TOKEN, transport=lambda *a: (201, b'{}'))
    with pytest.raises(GitHubError):
        odd.create_issue(req(), req().fingerprint, timeout=5)


def test_create_puts_marker_body_and_timeout_on_the_request(rest, gw):
    ref = gw.create_issue(req(), req().fingerprint, timeout=7.5)
    body = rest.issues[ref.number]['body']
    assert fingerprint_marker(req().fingerprint) in body and BODY_BEGIN in body and 'the body' in body
    assert rest.calls[-1] == ('POST', '/repos/owner/repo/issues', 7.5)


def test_connection_refused_is_create_not_sent_but_timeouts_are_not(rest, gw):
    rest.fail[('POST', r'/issues$')] = _NotSent()
    with pytest.raises(CreateNotSent):
        gw.create_issue(req(), req().fingerprint, timeout=5)
    rest.fail[('POST', r'/issues$')] = TimeoutError('slow')
    with pytest.raises(GitHubError) as caught:                 # uncertain: anything but CreateNotSent
        gw.create_issue(req(), req().fingerprint, timeout=5)
    assert not isinstance(caught.value, CreateNotSent)


def test_update_replaces_only_the_managed_section_and_is_idempotent(rest, gw):
    ref = gw.create_issue(req(), req().fingerprint, timeout=5)
    rest.issues[ref.number]['body'] = rest.issues[ref.number]['body'].replace(
        BODY_END, BODY_END + '\n\nHUMAN NOTE') 
    newer = req(body='changed body')
    gw.update_issue(ref.number, newer, 'reason a')
    body = rest.issues[ref.number]['body']
    assert 'changed body' in body and 'the body' not in body and 'HUMAN NOTE' in body
    before = len(rest.writes())
    gw.update_issue(ref.number, newer, 'reason a')
    assert len(rest.writes()) == before                       # no second PATCH, no second comment
    gw.update_issue(ref.number, newer, 'reason b')
    assert len(rest.writes()) == before + 1 and len(rest.comments[ref.number]) == 2


def test_update_backfills_marker_on_legacy_issue_and_keeps_human_text(rest, gw):
    rest.seed(11, 'human written legacy text')
    gw.update_issue(11, req(), 'adopted')
    body = rest.issues[11]['body']
    assert body.startswith('human written legacy text') and fingerprint_marker(req().fingerprint) in body


def test_update_of_missing_issue_raises(gw):
    with pytest.raises(GitHubError):
        gw.update_issue(404, req(), 'x')


def test_duplicate_documentation_is_a_single_comment_and_never_closes(rest, gw):
    rest.seed(22)
    assert not gw.is_documented_duplicate(22, 11)
    gw.mark_duplicate(22, 11)
    gw.mark_duplicate(22, 11)
    assert gw.is_documented_duplicate(22, 11) and not gw.is_documented_duplicate(22, 12)
    assert len(rest.comments[22]) == 1 and rest.issues[22]['state'] == 'open'


def test_reopen_only_opens_and_comments(rest, gw):
    rest.seed(30, state='closed')
    gw.reopen_issue(30, req(), 'retry')
    assert rest.issues[30]['state'] == 'open' and len(rest.comments[30]) == 1


def test_no_call_the_gateway_makes_can_close_an_issue(rest, gw, tmp_path):
    reg = TaskRegistry(str(tmp_path / 'r.db'))
    ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    ensure_task(req(body='v2'), reg, gw, claimant='w', trusted_authors=None)
    for method, path, _ in rest.calls:
        assert method in ('GET', 'POST', 'PATCH')
    assert all(payload.get('state') != 'closed' for payload in rest.issues.values())
    assert all(i['state'] == 'open' for i in rest.issues.values())


def test_end_to_end_create_then_update_never_makes_a_second_issue(rest, gw, tmp_path):
    reg = TaskRegistry(str(tmp_path / 'r.db'))
    first = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    again = ensure_task(req(title='reworded'), reg, gw, claimant='w', trusted_authors=None)
    lost = ensure_task(req(), TaskRegistry(str(tmp_path / 'new.db')), gw, claimant='w', trusted_authors=None)
    assert (first.outcome, again.outcome, lost.outcome) == (EnsureOutcome.CREATED, EnsureOutcome.UPDATED, EnsureOutcome.RECOVERED)
    assert len(rest.issues) == 1 and first.issue_number == again.issue_number == lost.issue_number


def test_github_outage_during_lookup_blocks_nothing_and_creates_nothing(rest, gw, tmp_path):
    rest.fail[('GET', r'/issues$')] = 503
    reg = TaskRegistry(str(tmp_path / 'r.db'))
    with pytest.raises(GitHubError):
        ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert not rest.issues
    assert not [c for c in rest.calls if c[0] == 'POST']


def test_constructor_validates_repository_and_token():
    with pytest.raises(ValueError):
        GitHubRestGateway('not a repo', TOKEN)
    with pytest.raises(ValueError):
        GitHubRestGateway('owner/repo', '')


# ---- review round 1 of PR #130: redirects, wall-clock timeout, answer identity, 404 semantics ----
import http.client
import http.server
import socket
import threading
import time


def test_every_3xx_is_an_error_and_nothing_is_followed(rest, gw):
    rest.seed(11)
    rest.fail[('GET', r'/issues/11$')] = 301
    with pytest.raises(GitHubError):
        gw.get_issue(11)
    rest.fail[('PATCH', r'/issues/11$')] = 307
    with pytest.raises(GitHubError):
        gw._call('PATCH', '/repos/owner/repo/issues/11', {'body': 'x'})


def test_an_answer_for_another_issue_number_is_refused(rest, gw):
    rest.seed(11)
    rest.seed(77)
    rest.alias[11] = 77
    with pytest.raises(GitHubError):
        gw.get_issue(11)
    with pytest.raises(GitHubError):
        gw.update_issue(11, req(), 'x')
    assert not rest.writes()                                  # nothing was written to #77


def test_an_issue_of_another_repository_is_refused(rest, gw):
    rest.seed(5)
    rest.issues[5]['repository_url'] = 'https://api.github.com/repos/owner/other'
    with pytest.raises(GitHubError):
        gw.get_issue(5)
    rest.seed(6, fingerprint_marker(req().fingerprint))
    rest.issues[6]['repository_url'] = 'https://api.github.com/repos/owner/other'
    with pytest.raises(GitHubError):
        gw.find_issues(req().fingerprint, '')


def test_404_on_an_invisible_repository_is_not_reported_as_missing_issue(rest, gw):
    assert gw.get_issue(404) is None                          # repository visible: a real 404 for the issue
    rest.repo_visible = False
    with pytest.raises(GitHubError):
        GitHubRestGateway('owner/repo', TOKEN, transport=rest).get_issue(404)


def test_connection_refused_only_counts_as_not_sent_for_create(rest, gw):
    rest.fail[('GET', r'/issues/9$')] = _NotSent()
    with pytest.raises(GitHubError):
        gw.get_issue(9)
    rest.fail[('POST', r'/issues$')] = _NotSent()
    with pytest.raises(CreateNotSent):
        gw.create_issue(req(), req().fingerprint, timeout=5)


class _Server:
    """Local HTTP server for the real transport; `handler(self)` decides the answer."""
    def __init__(self, handler):
        self.paths = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass

            def do_GET(self): outer.paths.append(('GET', self.path)); handler(self)
            def do_POST(self):
                self.rfile.read(int(self.headers.get('Content-Length') or 0)); outer.paths.append(('POST', self.path)); handler(self)
            do_PATCH = do_POST

        self.httpd = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.url = f'http://127.0.0.1:{self.httpd.server_port}'
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def _real(server, **kw):
    return GitHubRestGateway('o/r', TOKEN, api=server.url, **kw)


def test_real_transport_does_not_follow_a_redirect_to_another_issue():
    def handler(h):
        if h.path.endswith('/issues/11'):
            h.send_response(301); h.send_header('Location', '/repos/o/r/issues/77'); h.send_header('Content-Length', '0'); h.end_headers()
        else:
            body = b'{"number": 77, "state": "open"}'
            h.send_response(200); h.send_header('Content-Length', str(len(body))); h.end_headers(); h.wfile.write(body)
    server = _Server(handler)
    try:
        with pytest.raises(GitHubError):
            _real(server).get_issue(11)
        assert server.paths == [('GET', '/repos/o/r/issues/11')]      # #77 was never requested
    finally:
        server.close()


def test_real_transport_slow_drip_answer_cannot_outlive_the_create_timeout():
    def handler(h):
        h.send_response(201); h.send_header('Content-Length', '200'); h.end_headers()
        for _ in range(200):
            try:
                h.wfile.write(b' '); h.wfile.flush()
            except OSError:
                return
            time.sleep(0.1)
    server = _Server(handler)
    try:
        gateway = _real(server)
        start = time.monotonic()
        with pytest.raises(GitHubError) as caught:
            gateway.create_issue(req(), req().fingerprint, timeout=0.6)
        assert time.monotonic() - start < 3 and not isinstance(caught.value, CreateNotSent)
        assert 'timed out after' in str(caught.value) and 'POST /repos/' in str(caught.value)    # the reason stays readable
    finally:
        server.close()


def test_real_transport_http_errors_and_refused_connections():
    server = _Server(lambda h: (h.send_response(403), h.send_header('Content-Length', '0'), h.end_headers()))
    try:
        with pytest.raises(GitHubError, match='HTTP 403'):
            _real(server).get_issue(1)
    finally:
        server.close()
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]                          # closed again: nothing listens here
    dead = GitHubRestGateway('o/r', TOKEN, api=f'http://127.0.0.1:{port}')
    with pytest.raises(CreateNotSent):
        dead.create_issue(req(), req().fingerprint, timeout=2)
    with pytest.raises(GitHubError):
        dead.get_issue(1)


def test_real_transport_refuses_plain_http_to_a_real_host():
    with pytest.raises(GitHubError):
        GitHubRestGateway('o/r', TOKEN, api='http://example.com').get_issue(1)


# ---- review round 2 of PR #130 ----
def test_repository_check_is_not_cached(rest, gw):
    assert gw.get_issue(404) is None
    rest.repo_visible = False
    with pytest.raises(GitHubError):
        gw.get_issue(404)


def test_patch_and_reopen_answers_must_name_the_asked_issue(rest):
    rest.seed(5, 'text')

    def transport(method, url, headers, body, timeout):
        if method == 'PATCH':
            return 200, b'{"number": 99, "state": "open"}'
        return rest(method, url, headers, body, timeout)
    gateway = GitHubRestGateway('owner/repo', TOKEN, transport=transport)
    with pytest.raises(GitHubError):
        gateway.update_issue(5, req(), 'x')
    with pytest.raises(GitHubError):
        gateway.reopen_issue(5, req(), 'x')


def test_a_request_the_caller_gave_up_on_during_connect_is_never_sent_later(monkeypatch):
    from src.task_governance import github_gateway

    class SlowConnect(http.client.HTTPConnection):
        def connect(self):
            super().connect()
            time.sleep(0.8)                                    # the caller times out meanwhile

    monkeypatch.setattr(github_gateway, 'HTTPConnection', SlowConnect)
    server = _Server(lambda h: (h.send_response(201), h.send_header('Content-Length', '2'), h.end_headers(), h.wfile.write(b'{}')))
    try:
        with pytest.raises(GitHubError):
            _real(server).create_issue(req(), req().fingerprint, timeout=0.2)
        time.sleep(2.5)                                        # long enough for a silent reconnect (0.8 s) plus send
        assert ('POST', '/repos/o/r/issues') not in server.paths
    finally:
        server.close()


def test_a_timeout_shuts_the_socket_down_so_a_send_in_progress_cannot_finish(monkeypatch):
    from src.task_governance import github_gateway
    seen = {}

    class Sock:
        def __init__(self):
            self.dead = threading.Event()

        def shutdown(self, how):
            seen['how'] = how
            self.dead.set()

    class HangingConn:
        def __init__(self, host, port, timeout=None):
            self.sock = None

        def connect(self):
            self.sock = Sock()

        def request(self, *args, **kwargs):
            seen['sent'] = not self.sock.dead.wait(5)             # a send blocked on a full buffer

        def getresponse(self):
            raise OSError('no answer')

        def close(self):
            seen['closed'] = True

    monkeypatch.setattr(github_gateway, 'HTTPConnection', HangingConn)
    start = time.monotonic()
    with pytest.raises(GitHubError):
        github_gateway._http_transport('POST', 'http://127.0.0.1:9/x', {}, b'{}', 0.3)
    time.sleep(0.2)
    assert time.monotonic() - start < 2 and seen['how'] == socket.SHUT_RDWR and seen['sent'] is False and seen['closed']


@pytest.mark.parametrize('error', [lambda headers: RuntimeError(f'failed with {headers}'),
                                   lambda headers: GitHubError(f'failed with {headers}')])
def test_an_injected_transport_cannot_leak_the_token_through_its_exception(error):
    def leaky(method, url, headers, body, timeout):
        raise error(headers)
    gateway = GitHubRestGateway('owner/repo', TOKEN, transport=leaky)
    with pytest.raises(GitHubError) as caught:
        gateway.get_issue(1)
    assert TOKEN not in str(caught.value) and TOKEN not in repr(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_an_unusable_issue_number_in_an_answer_is_a_github_error(rest):
    gateway = GitHubRestGateway('owner/repo', TOKEN, transport=lambda *a: (200, b'{"number": "x"}'))
    with pytest.raises(GitHubError):
        gateway.get_issue(1)


# -- the listing lags behind new issues (seen live against github.com) ---------------------------------------------

def test_a_lagging_listing_still_finds_the_issue_that_was_just_created(rest, gw, tmp_path):
    rest.next_number, rest.lag_listing = 0, True    # numbers are sequential on GitHub: the first issue is #1
    first = ensure_task(req(), TaskRegistry(str(tmp_path / 'a.db')), gw, claimant='w', trusted_authors=None)
    lost = ensure_task(req(), TaskRegistry(str(tmp_path / 'b.db')), gw, claimant='w', trusted_authors=None)
    assert first.outcome is EnsureOutcome.CREATED and lost.outcome is EnsureOutcome.RECOVERED
    assert len(rest.issues) == 1 and lost.issue_number == first.issue_number


def test_find_issues_sees_lagging_issues_below_and_above_the_highest_listed(rest, gw):
    fp = req().fingerprint
    for number in (1, 2, 3):
        rest.seed(number)
    rest.seed(4, fingerprint_marker(fp))          # below the highest listed number
    rest.seed(5)
    rest.seed(6, fingerprint_marker(fp))          # above it
    rest.unlisted = {4, 6}
    assert [i.number for i in gw.find_issues(fp, '')] == [4, 6]


def test_deleted_and_transferred_numbers_are_not_errors(rest, gw):
    rest.seed(1)
    rest.seed(4)                                   # 2 and 3 are gaps: one gone (404), one transferred (301)
    rest.fail[('GET', r'/issues/2$')] = 410
    rest.fail[('GET', r'/issues/3$')] = 301
    assert gw.find_issues('x' * 64, '') == []


def test_a_server_error_while_reading_a_gap_is_not_read_as_absent(rest, gw):
    rest.seed(1)
    rest.seed(3)
    rest.fail[('GET', r'/issues/2$')] = 503
    with pytest.raises(GitHubError):
        gw.find_issues('x' * 64, '')


def test_an_empty_repository_costs_only_a_few_direct_reads(rest, gw):
    assert gw.find_issues('x' * 64, '') == []
    assert [c[1] for c in rest.calls if '/issues/' in c[1]] == [f'/repos/owner/repo/issues/{n}' for n in (1, 2, 3)]


def test_a_long_run_of_unlisted_numbers_is_refused_instead_of_guessed(rest):
    for number in range(1, 700):
        rest.seed(number)
    rest.unlisted = set(range(1, 700))
    with pytest.raises(GitHubError, match='refusing to guess'):
        GitHubRestGateway('owner/repo', TOKEN, transport=rest).find_issues('x' * 64, '')


def test_the_post_create_check_reaches_the_new_issue_even_behind_three_missing_numbers(rest, gw, tmp_path):
    rest.next_number, rest.lag_listing = 0, True
    for number in range(1, 6):
        rest.seed(number)
    for number in (6, 7, 8):                       # deleted at the top: three misses in a row
        rest.fail[('GET', rf'/issues/{number}$')] = 410
    rest.next_number = 8
    first = ensure_task(req(), TaskRegistry(str(tmp_path / 'a.db')), gw, claimant='w', trusted_authors=None)
    assert first.outcome is EnsureOutcome.CREATED and first.issue_number == 9
    # a second creator that was blind to #9 before its own create must see it afterwards: loud, not a silent duplicate
    other = GitHubRestGateway('owner/repo', TOKEN, transport=rest)
    again = ensure_task(req(), TaskRegistry(str(tmp_path / 'b.db')), other, claimant='w2', trusted_authors=None)
    assert again.outcome is EnsureOutcome.BLOCKED and again.detail == 'DUPLICATE_AFTER_CREATE'
    assert len(rest.issues) == 7                   # exactly one extra issue (#10); the check named both


def test_a_marker_issue_far_below_the_highest_listed_number_is_still_found(rest, gw):
    fp = req().fingerprint
    for number in range(1, 101):
        rest.seed(number, fingerprint_marker(fp) if number == 40 else '', pr=number > 40)
    rest.unlisted = {40}                           # 60 pull requests landed after it while the listing lagged
    assert [i.number for i in gw.find_issues(fp, '')] == [40]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.mark.parametrize('status', [404, 410, 301])
def test_old_missing_numbers_are_remembered_only_after_two_answers_far_apart(rest, status):
    clock = Clock()
    gw = GitHubRestGateway('owner/repo', TOKEN, transport=rest, clock=clock)
    for number in range(1, 121):
        if number not in (3, 4):
            rest.seed(number)
    rest.fail[('GET', r'/issues/[34]$')] = status
    count = lambda: len([c for c in rest.calls if c[1].endswith(('/issues/3', '/issues/4'))])
    gw.find_issues('x' * 64, '')
    gw.find_issues('x' * 64, '')                  # a second answer right away does not count: still asked every time
    assert count() == 4
    clock.now += 121
    gw.find_issues('x' * 64, '')                  # the second answer, far enough apart: remembered from now on
    assert count() == 6
    gw.find_issues('x' * 64, '')
    assert count() == 6


def test_a_single_wrong_answer_never_hides_an_old_issue_for_good(rest):
    clock = Clock()
    gw = GitHubRestGateway('owner/repo', TOKEN, transport=rest, clock=clock)
    fp = req().fingerprint
    for number in range(1, 101):
        rest.seed(number, fingerprint_marker(fp) if number == 40 else '', pr=number > 40)
    rest.unlisted = {40}
    for status in (404, 410):
        rest.fail[('GET', r'/issues/40$')] = status       # one wrong answer while the issue is still hidden by the listing
        assert gw.find_issues(fp, '') == []
        del rest.fail[('GET', r'/issues/40$')]
        assert [i.number for i in gw.find_issues(fp, '')] == [40]
        clock.now += 1000                                  # even much later, a good answer in between resets nothing harmful


def test_the_post_create_check_is_not_cut_short_by_the_read_limit(rest, gw, tmp_path):
    for number in range(1, 101):
        rest.seed(number)
    rest.next_number, rest.lag_listing = 699, True
    for number in range(101, 700):
        rest.fail[('GET', rf'/issues/{number}$')] = 410
    result = ensure_task(req(), TaskRegistry(str(tmp_path / 'a.db')), gw, claimant='w', trusted_authors=None)
    assert result.outcome is EnsureOutcome.CREATED and result.issue_number == 700    # reached its own number, mapped, no error
    assert len([c for c in rest.calls if c[0] == 'POST']) == 1


def test_a_lookup_that_hits_the_read_limit_fails_before_anything_is_created(rest, gw, tmp_path):
    for number in (1, 700):
        rest.seed(number)                          # 698 numbers in between are missing (404): too many to read
    with pytest.raises(GitHubError, match='refusing to guess'):
        ensure_task(req(), TaskRegistry(str(tmp_path / 'a.db')), gw, claimant='w', trusted_authors=None)
    assert rest.writes() == [] and len(rest.issues) == 2


def test_an_implausible_issue_number_in_the_create_answer_maps_but_never_makes_lookups_walk_to_it(rest, gw):
    rest.next_number, rest.lag_listing = 999_999_999, True
    ref = gw.create_issue(req(), req().fingerprint, timeout=5)
    assert ref.number == 1_000_000_000 and gw._top == 0
    gw.find_issues('x' * 64, '')
    assert len(rest.calls) < 12                    # a few reads, not a walk of a billion numbers


def _failing_check_after_create(gw):
    real, calls = gw.find_issues, []

    def flaky(fingerprint, key):
        calls.append(1)
        if len(calls) == 2:                        # the lookup before the create works, the check after it does not
            raise GitHubError('GET /repos/owner/repo/issues: HTTP 429')
        return real(fingerprint, key)
    gw.find_issues = flaky


def test_a_failing_post_create_check_blocks_with_the_new_issue_and_the_next_run_adopts_it(rest, gw, tmp_path):
    reg = TaskRegistry(str(tmp_path / 'a.db'))
    _failing_check_after_create(gw)
    first = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert first.outcome is EnsureOutcome.BLOCKED and first.detail == 'POST_CREATE_CHECK_FAILED' and first.issue_number == 1
    assert first.mapping.block_candidates == (1,)
    assert 'POST_CREATE_CHECK_FAILED' in [i['reason'] for i in reg.incidents(req().fingerprint)]
    again = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert again.outcome in (EnsureOutcome.CREATED, EnsureOutcome.RECOVERED, EnsureOutcome.UPDATED) and again.issue_number == 1
    assert again.mapping.state is MappingState.MAPPED
    assert len([c for c in rest.calls if c[0] == 'POST' and c[1].endswith('/issues')]) == 1


def test_a_failing_post_create_check_with_a_hidden_older_marker_issue_documents_it_as_duplicate(rest, gw, tmp_path):
    rest.next_number, rest.lag_listing = 0, True
    for number in range(1, 6):
        rest.seed(number)
    rest.seed(9, fingerprint_marker(req().fingerprint))      # an older issue of this task, hidden by the lag
    rest.unlisted = {9}
    for number in (6, 7, 8):
        rest.fail[('GET', rf'/issues/{number}$')] = 410
    rest.next_number = 9
    reg = TaskRegistry(str(tmp_path / 'a.db'))
    _failing_check_after_create(gw)
    first = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert first.outcome is EnsureOutcome.BLOCKED and first.issue_number == 10
    again = ensure_task(req(), reg, gw, claimant='w', trusted_authors=None)
    assert again.mapping.state is MappingState.MAPPED and again.issue_number == 10
    assert any('TIM_DUPLICATE_OF:10' in c['body'] for c in rest.comments.get(9, []))     # #9 is documented, not closed
    assert rest.issues[9]['state'] == 'open'
    assert len([c for c in rest.calls if c[0] == 'POST' and c[1].endswith('/issues')]) == 1


def test_a_batch_of_creates_does_not_reread_its_own_issues_for_other_tasks(rest, gw, tmp_path):
    rest.lag_listing = True
    reg = TaskRegistry(str(tmp_path / 'a.db'))
    for index in range(40):
        ensure_task(req(target=f'T{index}'), reg, gw, claimant='w', trusted_authors=None)
    gets = len([c for c in rest.calls if c[0] == 'GET' and re.search(r'/issues/\d+$', c[1])])
    assert gets < 40 * 10                           # linear, not quadratic (a full re-read would be about 40 * 40)


def test_an_answer_other_than_200_on_a_direct_read_is_an_error(rest, gw):
    rest.seed(1)
    rest.seed(3)
    rest.fail[('GET', r'/issues/2$')] = 202
    with pytest.raises(GitHubError, match='unexpected HTTP 202'):
        gw.find_issues('x' * 64, '')


def test_a_remembered_missing_number_is_asked_again_after_an_hour(rest):
    clock = Clock()
    gw = GitHubRestGateway('owner/repo', TOKEN, transport=rest, clock=clock)
    for number in range(1, 121):
        if number != 3:
            rest.seed(number)
    rest.fail[('GET', r'/issues/3$')] = 410
    count = lambda: len([c for c in rest.calls if c[1].endswith('/issues/3')])
    gw.find_issues('x' * 64, '')
    clock.now += 121
    gw.find_issues('x' * 64, '')
    assert count() == 2
    gw.find_issues('x' * 64, '')
    assert count() == 2                            # remembered
    clock.now += 3600
    gw.find_issues('x' * 64, '')
    assert count() == 3                            # asked again after the time to live

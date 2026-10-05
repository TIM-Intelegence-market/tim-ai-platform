"""Worker identity, recovery of aborted runs and branch maintenance of the issue runner (real git, simulated gh)."""
import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.github_issue_pipeline import (CommandRunner, Leftover, Pipeline, PipelineError, WorkerIdentity,
                                           load_worker_identity, protected_path)

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
BRANCH = "claude/issue-7-fix-race"
ISSUE = json.dumps([{"number": 7, "title": "Fix race", "state": "OPEN", "body": "",
                     "labels": [{"name": "priority:p0"}, {"name": "status:ready"}, {"name": "agent:pilot"}],
                     "updatedAt": "2026-09-27T10:00:00Z", "url": "https://example.test/7"}])


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-c", "commit.gpgsign=false", *args], cwd=cwd, check=check, capture_output=True,
                          text=True, env={**os.environ, **GIT_ENV}).stdout.strip()


class Hybrid(CommandRunner):
    """git runs for real, gh/claude/codex are simulated and recorded."""

    def __init__(self, repo, *, login="tim-worker", permissions='{"admin": false, "maintain": false, "push": true}',
                 prs=None, pr_state=None, on_update=None, views=None, pr_after_create=False):
        self.repo, self.login, self.permissions = repo, login, permissions
        self.calls, self.envs, self.prs, self.pr_state = [], [], prs or [], pr_state or {}
        self.on_update, self.views, self.pr_after_create = on_update, list(views or []), pr_after_create

    def issued(self, *prefix):
        return [call for call in self.calls if call[:len(prefix)] == list(prefix)]

    def run(self, args, *, cwd=None, timeout=900, env=None):
        args = list(args)
        self.calls.append(args)
        self.envs.append(env)
        if args[0] == "git":
            full_env = {**os.environ, **GIT_ENV, **(env or {})}
            done = subprocess.run(args, cwd=cwd, check=False, capture_output=True, text=True, env=full_env)
            if done.returncode:
                raise PipelineError(done.stderr.strip()[:500])
            return done.stdout.strip()
        if args[0] in {"codex", "claude"} and args[1:3] != ["auth", "status"]:
            raise AssertionError(f"{args[0]} must not run here")
        if args[:2] == ["claude", "auth"]:
            return json.dumps({"loggedIn": True})
        if args[:3] == ["gh", "issue", "list"]:
            return ISSUE
        if args[:3] == ["gh", "repo", "view"] and "nameWithOwner" in args:
            return "owner/repo"
        if args[:3] == ["gh", "repo", "view"]:
            return '{"defaultBranchRef":{"name":"platform-main"}}'
        if args[:3] == ["gh", "api", "graphql"]:
            return self.login
        if args[:2] == ["gh", "api"] and ".permissions" in args:
            return self.permissions
        if args[:3] == ["gh", "api", "-X"] and "update-branch" in args[4]:
            if self.on_update:
                self.on_update()
            return "{}"
        if args[:3] == ["gh", "pr", "view"]:
            return json.dumps(self.views.pop(0) if len(self.views) > 1 else self.views[0])
        if args[:3] == ["gh", "pr", "create"]:
            self.pr_state["created"] = True
            return ""
        if args[:3] == ["gh", "pr", "list"]:
            if "--head" in args:
                visible = self.pr_state.get("created") or not self.pr_after_create
                return json.dumps(self.prs if visible else [])
            return json.dumps(self.prs)
        return ""


@pytest.fixture
def world(tmp_path, monkeypatch):
    monkeypatch.setattr("scripts.github_issue_pipeline.shutil.which", lambda _: "/bin/tool")
    origin, repo, state = tmp_path / "origin.git", tmp_path / "repo", tmp_path / "state"
    git(tmp_path, "init", "-q", "--bare", "-b", "platform-main", str(origin))
    git(tmp_path, "clone", "-q", str(origin), str(repo))
    git(repo, "checkout", "-q", "-b", "platform-main")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("x = 1\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    git(repo, "push", "-q", "-u", "origin", "platform-main")
    git(repo, "fetch", "-q", "origin")
    worker = WorkerIdentity("tim-worker", "test-token", tmp_path / "gh-config")
    return type("World", (), {"origin": origin, "repo": repo, "state": state, "worker": worker, "tmp": tmp_path})


def pipeline(world, runner, worker=True):
    return Pipeline(world.repo, world.state, runner, worker=world.worker if worker else None, sleep=lambda s: None)


def add_worktree(world, commit=False, push=False):
    path = world.state / "worktrees" / "issue-7-old"
    path.parent.mkdir(parents=True, exist_ok=True)
    git(world.repo, "worktree", "add", "-q", "-b", BRANCH, str(path), "origin/platform-main")
    if commit:
        (path / "src" / "b.py").write_text("y = 2\n")
        git(path, "add", "-A")
        git(path, "commit", "-qm", "work")
    if push:
        git(path, "push", "-q", "origin", BRANCH)
    return path


def pr_for(world, path, author="tim-worker", draft=True):
    head = git(path, "rev-parse", "HEAD")
    return [{"number": 9, "url": "https://example.test/pr/9", "headRefOid": head, "headRefName": BRANCH,
             "baseRefName": "platform-main", "isDraft": draft, "author": {"login": author},
             "body": "Closes #7\n<!-- TIM_CODEX_CLAUDE_RUN_V1 -->"}]


# --- identity ------------------------------------------------------------------------------------------

def test_worker_identity_is_all_or_nothing_and_validated(tmp_path):
    assert load_worker_identity({}, tmp_path) is None
    for env in ({"TIM_WORKER_GH_TOKEN": "t"}, {"TIM_WORKER_LOGIN": "w"}, {"TIM_WORKER_GH_TOKEN": "t u", "TIM_WORKER_LOGIN": "w"},
                {"TIM_WORKER_GH_TOKEN": "t", "TIM_WORKER_LOGIN": "bad login"}, {"TIM_WORKER_GH_TOKEN": "t", "TIM_WORKER_LOGIN": "-x"}):
        with pytest.raises(PipelineError):
            load_worker_identity(env, tmp_path)
    identity = load_worker_identity({"TIM_WORKER_GH_TOKEN": "secret-token", "TIM_WORKER_LOGIN": "tim-worker[bot]"}, tmp_path)
    assert identity.login == "tim-worker[bot]" and "secret-token" not in repr(identity)
    assert oct(identity.config_dir.stat().st_mode & 0o777) == "0o700"


def test_gh_and_git_act_as_the_worker_but_codex_and_claude_never_see_the_token(world, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "owner-token")
    monkeypatch.setenv("GH_TOKEN", "owner-gh-token")
    monkeypatch.setenv("TIM_WORKER_GH_TOKEN", "test-token")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "credential.helper")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "!malicious-helper")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    runner = Hybrid(world.repo)
    p = pipeline(world, runner)
    p.github("issue", "list")
    p.command("git", "status")
    p.command("claude", "auth", "status")
    gh_env, git_env, claude_env = runner.envs[0], runner.envs[1], runner.envs[2]
    for env in (gh_env, git_env):
        assert env["GH_TOKEN"] == "test-token" and env["GH_CONFIG_DIR"] == str(world.worker.config_dir)
        assert "GITHUB_TOKEN" not in env and env["GIT_TERMINAL_PROMPT"] == "0"
        pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))}
        assert pairs["credential.helper"] == "!gh auth git-credential"
    assert claude_env is not None
    assert not (set(claude_env) & {"TIM_WORKER_GH_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "GIT_CONFIG_COUNT",
                                  "GIT_CONFIG_KEY_0", "GIT_CONFIG_VALUE_0"})
    assert claude_env.get("PATH") == os.environ.get("PATH")


def test_the_hardened_worktree_env_keeps_its_settings_next_to_the_worker_credentials(world):
    runner = Hybrid(world.repo)
    p = pipeline(world, runner)
    p.worktree_git(world.repo, world.repo / ".git", "status")
    env = runner.envs[-1]
    assert env["GIT_CONFIG_KEY_0"] == "core.hooksPath" and env["GIT_CONFIG_KEY_1"] == "core.fsmonitor"
    assert env["GIT_CONFIG_COUNT"] == "4" and env["GIT_DIR"] == str(world.repo / ".git")


def test_a_real_run_without_a_worker_identity_stops_before_any_write(world):
    runner = Hybrid(world.repo)
    with pytest.raises(PipelineError, match="worker identity is required"):
        pipeline(world, runner, worker=False).execute(mode="pilot")
    assert not [c for c in runner.calls if c[:2] in (["gh", "label"], ["gh", "issue"]) and c[2] in ("create", "edit", "comment")]


@pytest.mark.parametrize("kwargs, message", [
    ({"login": "tim-owner"}, "not as the worker identity"),
    ({"permissions": '{"admin": true, "maintain": true, "push": true}'}, "lacks admin"),
    ({"permissions": '{"admin": false, "maintain": true}'}, "lacks admin"),
    ({"permissions": "null"}, "lacks admin"),
    ({"permissions": "{}"}, "lacks admin"),
    ({"permissions": "not json"}, "could not be read"),
])
def test_wrong_identity_or_elevated_rights_stop_the_run(world, kwargs, message):
    with pytest.raises(PipelineError, match=message):
        pipeline(world, Hybrid(world.repo, **kwargs)).verify_worker_identity()


def test_a_correct_worker_identity_passes():
    pipeline_ = Pipeline(Path("."), Path("."), Hybrid(Path(".")), worker=WorkerIdentity("Tim-Worker", "t", Path(".")))
    pipeline_.verify_worker_identity()


def test_a_draft_pr_by_someone_else_is_refused(world):
    path = add_worktree(world, commit=True, push=True)
    runner = Hybrid(world.repo, prs=pr_for(world, path, author="tim-owner"))
    leftover, branch = pipeline(world, runner).inspect_leftover(__import__("types").SimpleNamespace(number=7, title="Fix race"), "origin/platform-main")
    with pytest.raises(PipelineError, match="not the worker identity"):
        pipeline(world, runner).finish_existing(__import__("types").SimpleNamespace(number=7, title="Fix race"), leftover, branch, "origin/platform-main")


# --- recovery of an aborted run (real git) -----------------------------------------------------------------

def run_execute(world, runner):
    return pipeline(world, runner).execute(mode="pilot")


def test_nothing_left_over_runs_the_normal_flow_up_to_codex(world):
    class Stop(Hybrid):
        def run(self, args, **kw):
            if list(args)[0] == "codex":
                self.calls.append(list(args))
                raise PipelineError("codex reached")  # the fresh flow started: that is all this test needs
            return super().run(args, **kw)

    runner = Stop(world.repo)
    assert run_execute(world, runner) == 1
    assert runner.issued("codex")


def test_an_empty_leftover_branch_is_discarded_with_a_record_and_the_flow_starts_fresh(world):
    add_worktree(world)

    class Stop(Hybrid):
        def run(self, args, **kw):
            if list(args)[0] == "codex":
                self.calls.append(list(args))
                raise PipelineError("codex reached")
            return super().run(args, **kw)

    runner = Stop(world.repo)
    run_execute(world, runner)
    assert runner.issued("git", "worktree", "remove", "--force") and runner.issued("git", "branch", "-D", BRANCH)
    assert list((world.state / "runs").glob("*-discarded.patch"))
    assert not git(world.repo, "branch", "--list", BRANCH)


def test_committed_but_unpushed_work_is_pushed_and_the_draft_pr_is_opened_without_rerunning_agents(world):
    path = add_worktree(world, commit=True)
    runner = Hybrid(world.repo, prs=pr_for(world, path), pr_state={}, pr_after_create=True)
    assert run_execute(world, runner) == 0
    assert git(world.origin, "rev-parse", f"refs/heads/{BRANCH}") == git(path, "rev-parse", "HEAD")
    assert runner.issued("git", "push") and runner.issued("gh", "pr", "create")
    assert not runner.issued("codex") and not runner.issued("claude", "-p")
    assert ["gh", "issue", "edit", "7", "--add-label", "agent:pr-open", "--remove-label", "agent:claude-running"] in runner.calls


def test_already_pushed_work_only_needs_the_draft_pr(world):
    path = add_worktree(world, commit=True, push=True)
    runner = Hybrid(world.repo, prs=pr_for(world, path))
    assert run_execute(world, runner) == 0
    assert not runner.issued("git", "push") and not runner.issued("codex")
    assert runner.issued("gh", "issue", "comment")


def test_recovery_ignores_a_hostile_dot_git_file_in_the_leftover_worktree(world, tmp_path):
    path = add_worktree(world, commit=True)
    prs = pr_for(world, path)  # read before the worker's .git file is destroyed below
    evil = path / ".evil"
    evil.mkdir()
    marker = tmp_path / "MARKER"
    (evil / "config").write_text('[core]\n\tsshCommand = sh -c "echo x > %s; exit 1" --\n[remote "origin"]\n\turl = ssh://example.invalid/x\n' % marker)
    (path / ".git").write_text(f"gitdir: {evil}\n")
    runner = Hybrid(world.repo, prs=prs)
    # the commit's head is read through the trusted admin directory, never through the rewritten .git file
    assert pipeline(world, runner).trusted_gitdir(path).parent.name == "worktrees"
    run_execute(world, runner)
    assert not marker.exists()


@pytest.mark.parametrize("hostile", [".github/workflows/x.yml", "CLAUDE.md", "scripts/github_issue_pipeline.py", ".claude/s.json"])
def test_recovery_rechecks_the_committed_diff_and_pushes_nothing_unsafe(world, hostile):
    path = add_worktree(world)
    target = path / hostile
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x\n")
    git(path, "add", "-A", "-f")
    git(path, "commit", "-qm", "bad")
    runner = Hybrid(world.repo)
    assert run_execute(world, runner) == 1
    assert not runner.issued("git", "push") and not git(world.origin, "branch", "--list", BRANCH)
    comment = next(c for c in runner.issued("gh", "issue", "comment") if "Automation blocked" in c[-1])
    assert "protected path" in comment[-1] and "Kept for recovery" in comment[-1]


def test_recovery_with_uncommitted_changes_is_left_to_a_human(world):
    path = add_worktree(world, commit=True)
    (path / "src" / "dirty.py").write_text("z = 3\n")
    runner = Hybrid(world.repo)
    assert run_execute(world, runner) == 1
    assert not runner.issued("git", "push") and not runner.issued("gh", "pr", "create")


def test_remote_only_or_diverged_branches_are_never_touched(world):
    path = add_worktree(world, commit=True, push=True)
    other = world.tmp / "other"
    git(world.tmp, "clone", "-q", str(world.origin), str(other))
    git(other, "checkout", "-q", BRANCH)
    (other / "src" / "c.py").write_text("w = 4\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "someone else")
    git(other, "push", "-q", "origin", BRANCH)
    runner = Hybrid(world.repo)
    assert run_execute(world, runner) == 1  # diverged
    git(world.repo, "worktree", "remove", "--force", str(path))
    git(world.repo, "branch", "-D", BRANCH)
    runner = Hybrid(world.repo)
    assert run_execute(world, runner) == 1  # exists only on origin
    assert not runner.issued("git", "push") and not runner.issued("codex")


def test_the_gitdir_comes_from_the_main_repository_and_an_unregistered_worktree_is_an_error(world, tmp_path):
    path = add_worktree(world, commit=True)
    assert pipeline(world, Hybrid(world.repo)).trusted_gitdir(path) == Path(git(path, "rev-parse", "--absolute-git-dir"))
    with pytest.raises(PipelineError, match="No administrative git directory"):
        pipeline(world, Hybrid(world.repo)).trusted_gitdir(tmp_path / "elsewhere")


# --- keeping open worker PRs current ----------------------------------------------------------------------

def behind_pr(world, number=9, author="tim-worker", branch=BRANCH, base="platform-main", status="BEHIND"):
    head = git(world.repo, "rev-parse", "origin/platform-main")
    return {"number": number, "headRefName": branch, "headRefOid": head, "baseRefName": base, "mergeStateStatus": status,
            "author": {"login": author}}


def advance_base_and_update_branch(world):
    """Simulate GitHub's update-branch: the branch gets the new base merged in."""
    other = world.tmp / "updater"
    git(world.tmp, "clone", "-q", str(world.origin), str(other))
    git(other, "checkout", "-q", "platform-main")
    (other / "src" / "base_news.py").write_text("n = 1\n")
    git(other, "add", "-A")
    git(other, "commit", "-qm", "base moved")
    git(other, "push", "-q", "origin", "platform-main")
    git(other, "checkout", "-q", "-b", "tmp", "origin/" + BRANCH)
    git(other, "merge", "-q", "--no-edit", "platform-main")
    git(other, "push", "-q", "origin", f"tmp:{BRANCH}")
    return git(other, "rev-parse", "HEAD")


def make_branch_on_origin(world, files=None):
    path = add_worktree(world, commit=False)
    for name, content in (files or {"src/b.py": "y = 2\n"}).items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
    git(path, "add", "-A", "-f")
    git(path, "commit", "-qm", "work")
    git(path, "push", "-q", "origin", BRANCH)
    return git(path, "rev-parse", "HEAD")


def view(head, status="CLEAN", author="tim-worker", branch=BRANCH, base="platform-main"):
    return {"headRefOid": head, "headRefName": branch, "baseRefName": base, "mergeStateStatus": status,
            "author": {"login": author}}


def test_a_behind_worker_pr_is_updated_with_the_expected_head_and_re_checked(world, capsys):
    old = make_branch_on_origin(world)
    pr = behind_pr(world)
    pr["headRefOid"] = old
    state = {}
    runner = Hybrid(world.repo, prs=[pr], views=[view(old), view(old), "placeholder"])
    new_head = None

    def update():
        nonlocal new_head
        new_head = advance_base_and_update_branch(world)
        runner.views[:] = [view(new_head)]

    runner.on_update = update
    assert pipeline(world, runner).maintain_prs() == 0
    update_call = runner.issued("gh", "api", "-X", "PUT")[0]
    assert update_call[4] == "repos/owner/repo/pulls/9/update-branch" and update_call[-1] == f"expected_head_sha={old}"
    assert "branch updated and re-checked" in capsys.readouterr().out


@pytest.mark.parametrize("pr", [
    {"author": {"login": "someone"}}, {"headRefName": "feature/x"}, {"baseRefName": "main"}, {"mergeStateStatus": "CLEAN"},
    {"mergeStateStatus": "DIRTY"}, {"author": None},
])
def test_only_behind_worker_prs_on_the_worker_branch_pattern_are_touched(world, pr):
    runner = Hybrid(world.repo, prs=[{**behind_pr(world), **pr}])
    assert pipeline(world, runner).maintain_prs() == 0
    assert not runner.issued("gh", "api", "-X")


def test_conflicts_after_the_update_block_and_need_a_new_worker_run(world, capsys):
    old = make_branch_on_origin(world)
    runner = Hybrid(world.repo, prs=[{**behind_pr(world), "headRefOid": old}], views=[view("f" * 40, status="DIRTY")])
    assert pipeline(world, runner).maintain_prs() == 1
    assert "merge conflicts" in capsys.readouterr().out


def test_an_update_that_is_not_visible_yet_is_retried_on_the_next_run_not_trusted(world, capsys):
    old = make_branch_on_origin(world)
    runner = Hybrid(world.repo, prs=[{**behind_pr(world), "headRefOid": old}], views=[view(old)])
    assert pipeline(world, runner).maintain_prs() == 0
    assert "not visible yet" in capsys.readouterr().out and not runner.issued("git", "fetch", "--no-tags")


def test_the_identity_of_the_pr_must_not_change_during_the_update(world, capsys):
    old = make_branch_on_origin(world)
    runner = Hybrid(world.repo, prs=[{**behind_pr(world), "headRefOid": old}], views=[view("e" * 40, author="intruder")])
    assert pipeline(world, runner).maintain_prs() == 1
    assert "changed identity" in capsys.readouterr().out


@pytest.mark.parametrize("files", [{".github/workflows/x.yml": "a: b\n"}, {"CLAUDE.md": "x\n"}])
def test_the_updated_branch_is_re_validated_and_protected_paths_block(world, capsys, files):
    old = make_branch_on_origin(world, files)
    runner = Hybrid(world.repo, prs=[{**behind_pr(world), "headRefOid": old}], views=[view(old), view(old)])

    def update():
        runner.views[:] = [view(advance_base_and_update_branch(world))]

    runner.on_update = update
    assert pipeline(world, runner).maintain_prs() == 1
    assert "protected" in capsys.readouterr().out


def test_the_updated_branch_with_a_symlink_blocks(world, capsys):
    path = add_worktree(world)
    (path / "src" / "link.py").symlink_to("/etc/passwd")
    git(path, "add", "-A")
    git(path, "commit", "-qm", "link")
    git(path, "push", "-q", "origin", BRANCH)
    old = git(path, "rev-parse", "HEAD")
    runner = Hybrid(world.repo, prs=[{**behind_pr(world), "headRefOid": old}], views=[view(old)])
    runner.on_update = lambda: runner.views.__setitem__(slice(None), [view(advance_base_and_update_branch(world))])
    assert pipeline(world, runner).maintain_prs() == 1
    assert "non-regular" in capsys.readouterr().out


def test_maintenance_needs_the_worker_identity(world):
    with pytest.raises(PipelineError, match="worker identity is required"):
        pipeline(world, Hybrid(world.repo), worker=False).maintain_prs()


def test_protected_path_helper_matches_the_documented_rules():
    for raw in (".git/config", ".GITHUB/x", ".claude/a", "AGENTS.md", "Claude.md", "scripts/github_issue_pipeline.py", "/abs", "../x", ""):
        assert protected_path(raw)
    for raw in ("src/a.py", "tests/test_a.py", "docs/x.md", "scripts/other.py"):
        assert not protected_path(raw)


def test_leftover_dataclass_defaults():
    assert Leftover("none").worktree is None and Leftover("none").gitdir is None

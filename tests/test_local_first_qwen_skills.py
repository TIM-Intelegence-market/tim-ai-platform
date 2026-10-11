from __future__ import annotations

from pathlib import Path

from src.local_first import qwen_skills

REPO = Path(__file__).resolve().parents[1]


def write_skill(root, name, applies, body="Do the thing.", description="A skill."):
    folder = root / "config/qwen-skills" / name
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\nmetadata:\n  tim-applies-to: \"{applies}\"\n---\n\n{body}\n")


def test_repository_skills_load_and_follow_the_format():
    skills = {skill["name"]: skill for skill in qwen_skills.load_skills(REPO)}
    assert {"tim-offline-tests", "tim-search-replace-edits", "tim-safety-boundaries",
            "tim-tool-use", "tim-local-first-code"} <= set(skills)
    assert all(skill["applies_to"] and skill["body"] for skill in skills.values())


def test_selection_by_path_and_mode(tmp_path):
    write_skill(tmp_path, "always-on", "always")
    write_skill(tmp_path, "tools-only", "tool-loop")
    write_skill(tmp_path, "tests-only", "tests/**")
    write_skill(tmp_path, "db-only", "src/database/**")
    task = {"allowed_paths": ["src/a.py"], "tests": ["tests/test_a.py"]}
    assert [s["name"] for s in qwen_skills.skills_for(tmp_path, task)] == ["always-on", "tests-only"]
    assert [s["name"] for s in qwen_skills.skills_for(tmp_path, task, tool_loop=True)] == [
        "always-on", "tests-only", "tools-only"]


def test_invalid_or_mismatched_skills_are_ignored(tmp_path):
    write_skill(tmp_path, "good", "always")
    bad = tmp_path / "config/qwen-skills/renamed"
    bad.mkdir()
    (bad / "SKILL.md").write_text("---\nname: other\ndescription: x\n---\nbody\n")
    nofront = tmp_path / "config/qwen-skills/nofront"
    nofront.mkdir()
    (nofront / "SKILL.md").write_text("just text\n")
    assert [s["name"] for s in qwen_skills.load_skills(tmp_path)] == ["good"]


def test_symlinked_skills_are_ignored(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    write_skill(outside, "evil", "always")
    (tmp_path / "config/qwen-skills").mkdir(parents=True)
    (tmp_path / "config/qwen-skills/evil").symlink_to(outside / "config/qwen-skills/evil")
    assert qwen_skills.load_skills(tmp_path) == []


def test_total_size_is_bounded(tmp_path):
    for index in range(4):
        write_skill(tmp_path, f"big-{index}", "always", body="x" * 3000)
    selected = qwen_skills.skills_for(tmp_path, {"allowed_paths": ["src/a.py"]})
    assert sum(len(s["instructions"]) for s in selected) <= qwen_skills.MAX_TOTAL_CHARS
    assert all(s["trust"].startswith("TIM_REPOSITORY_GUIDANCE") for s in selected)

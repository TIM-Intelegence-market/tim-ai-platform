from dataclasses import replace

import pytest

from src.agent_infra.profiles import COMMON_FORBIDDEN
from src.agents.contract import (
    AgentSpec,
    Message,
    PolicyViolation,
    ReplayMismatch,
    RunRecord,
    TaskRecord,
    TaskStatus,
    canonical_json,
    content_hash,
    replay,
    run_task,
)

AT = "2026-09-29T20:00:00+00:00"


def spec(**overrides):
    values = dict(name="demo-agent", version="1.0.0", mission="Count supplied items.",
                  owner="uzi", allowed_actions=("read_snapshot", "write_report"),
                  tools=("pytest",), max_input_bytes=200)
    values.update(overrides)
    return AgentSpec(**values)


def count_handler(task_input):
    return {"count": len(task_input["items"]), "items": sorted(task_input["items"])}


# canonical JSON / hashing

def test_hash_is_independent_of_key_order():
    assert content_hash({"b": 1, "a": [1, 2]}) == content_hash({"a": [1, 2], "b": 1})
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


@pytest.mark.parametrize("value", [{"x": float("nan")}, {"x": {1, 2}}, {"x": object()}])
def test_non_json_values_are_rejected_not_stringified(value):
    with pytest.raises((TypeError, ValueError)):
        content_hash(value)


# AgentSpec

def test_spec_defaults_to_common_forbidden_actions():
    assert set(COMMON_FORBIDDEN) <= set(spec().forbidden_actions)


def test_spec_cannot_drop_common_forbidden_actions():
    with pytest.raises(ValueError, match="cannot be removed"):
        spec(forbidden_actions=("order_creation",))


def test_spec_rejects_action_both_allowed_and_forbidden():
    with pytest.raises(ValueError, match="both allowed and forbidden"):
        spec(allowed_actions=("read_snapshot", "trading_actions"))


@pytest.mark.parametrize("overrides", [
    {"version": "1.0"}, {"name": ""}, {"mission": " "}, {"allowed_actions": ()},
    {"allowed_actions": ["read_snapshot"]}, {"allowed_actions": ("a", "a")},
    {"timeout_seconds": 0}, {"timeout_seconds": 3601}, {"timeout_seconds": True},
    {"max_input_bytes": 0}, {"max_input_bytes": 1.5},
])
def test_spec_rejects_invalid_values(overrides):
    with pytest.raises(ValueError):
        spec(**overrides)


def test_authorize_rejects_forbidden_and_ungranted_actions():
    agent = spec()
    agent.authorize("read_snapshot")
    with pytest.raises(PolicyViolation, match="forbidden"):
        agent.authorize("order_creation")
    with pytest.raises(PolicyViolation, match="not granted"):
        agent.authorize("delete_everything")


def test_spec_hash_changes_with_grants():
    assert spec().spec_hash == spec().spec_hash
    assert spec().spec_hash != spec(allowed_actions=("read_snapshot",)).spec_hash


# TaskRecord

def task():
    return TaskRecord.new("task-1", "demo-agent", {"items": ["b", "a"]}, at=AT)


def test_task_lifecycle_is_versioned_and_immutable():
    created = task()
    ready = created.transition("READY", at=AT)
    running = ready.transition(TaskStatus.RUNNING, at=AT)
    done = running.transition("DONE", output={"count": 2}, at=AT)
    assert [created.revision, ready.revision, running.revision, done.revision] == [1, 2, 3, 4]
    assert created.status == TaskStatus.NEW and done.status == TaskStatus.DONE
    assert [h.status for h in done.history] == ["NEW", "READY", "RUNNING", "DONE"]
    assert done.output == {"count": 2}
    with pytest.raises(AttributeError):
        done.status = TaskStatus.NEW


def test_task_input_cannot_be_mutated_through_accessor():
    record = task()
    record.input["items"].append("c")
    assert record.input == {"items": ["b", "a"]}


@pytest.mark.parametrize("path", [["DONE"], ["READY", "DONE"], ["CANCELLED", "READY"]])
def test_invalid_transitions_are_rejected(path):
    record = task()
    with pytest.raises(ValueError):
        for target in path:
            record = record.transition(target, note="x", output={} if target == "DONE" else None,
                                       at=AT)


def test_done_requires_output_and_failure_requires_note():
    running = task().transition("READY", at=AT).transition("RUNNING", at=AT)
    with pytest.raises(ValueError, match="output"):
        running.transition("DONE", at=AT)
    with pytest.raises(ValueError, match="note"):
        running.transition("FAILED", at=AT)
    with pytest.raises(ValueError, match="output"):
        running.transition("FAILED", note="boom", output={"x": 1}, at=AT)


def test_task_rejects_naive_timestamps_self_dependency_and_bad_priority():
    with pytest.raises(ValueError):
        TaskRecord.new("t", "o", {}, at="2026-09-29T20:00:00")
    with pytest.raises(ValueError):
        TaskRecord.new("t", "o", {}, dependencies=("t",), at=AT)
    with pytest.raises(ValueError):
        TaskRecord.new("t", "o", {}, priority="P9", at=AT)
    with pytest.raises(ValueError):
        TaskRecord.new("t", "o", ["not", "a", "mapping"], at=AT)


def test_task_round_trip_and_tampered_history_is_rejected():
    done = (task().transition("READY", at=AT).transition("RUNNING", at=AT)
            .transition("DONE", output={"count": 2}, at=AT))
    restored = TaskRecord.from_dict(done.to_dict())
    assert restored == done and restored.record_hash == done.record_hash
    tampered = done.to_dict()
    tampered["history"] = [tampered["history"][0], tampered["history"][-1]]
    tampered["revision"] = 2
    with pytest.raises(ValueError, match="invalid transition"):
        TaskRecord.from_dict(tampered)
    with pytest.raises(ValueError, match="status/revision"):
        replace(done, revision=7)
    with pytest.raises(ValueError, match="status/revision"):
        replace(task(), revision=True)


# Message

def message(**overrides):
    values = dict(sender="demo-agent", recipient="review-agent", schema="demo.result.v1",
                  payload={"count": 2}, correlation_id="corr-1", timestamp=AT)
    values.update(overrides)
    return Message.create(**values)


def test_message_hash_is_deterministic_and_verified():
    first, second = message(), message(payload={"count": 2})
    assert first.hash == second.hash and len(first.hash) == 64
    assert Message.from_dict(first.to_dict()) == first
    assert message(correlation_id="corr-2").hash != first.hash


@pytest.mark.parametrize("field,value", [("payload", {"count": 3}), ("recipient", "x"),
                                          ("hash", "0" * 64), ("version", "9.9.9")])
def test_tampered_message_is_rejected(field, value):
    data = message().to_dict()
    data[field] = value
    with pytest.raises(ValueError):
        Message.from_dict(data)


def test_message_requires_correlation_id_and_timezone():
    with pytest.raises(ValueError):
        message(correlation_id="")
    with pytest.raises(ValueError):
        message(timestamp="2026-09-29T20:00:00")
    with pytest.raises(ValueError):
        message(timestamp="")


def test_message_payload_size_is_bounded():
    with pytest.raises(ValueError, match="size limit"):
        message(payload={"blob": "x" * (16 * 1024 * 1024)})


# run_task / replay

def test_run_task_is_deterministic_and_replayable():
    agent = spec()
    record = run_task(agent, count_handler, {"items": ["b", "a"]}, action="read_snapshot")
    again = run_task(agent, count_handler, {"items": ["b", "a"]}, action="read_snapshot")
    assert record == again
    assert record.to_dict()["output"] == {"count": 2, "items": ["a", "b"]}
    restored = RunRecord.from_dict(record.to_dict())
    assert replay(agent, count_handler, restored) == record


def test_run_task_enforces_policy_and_budget_before_handler():
    calls = []

    def handler(task_input):
        calls.append(task_input)
        return {}

    agent = spec()
    with pytest.raises(PolicyViolation):
        run_task(agent, handler, {}, action="order_creation")
    with pytest.raises(PolicyViolation, match="max_input_bytes"):
        run_task(agent, handler, {"items": ["x" * 500]}, action="read_snapshot")
    assert calls == []


def test_handler_must_return_json_object():
    with pytest.raises((TypeError, ValueError)):
        run_task(spec(), lambda _: ["not", "a", "mapping"], {}, action="read_snapshot")
    with pytest.raises((TypeError, ValueError)):
        run_task(spec(), lambda _: {"when": object()}, {}, action="read_snapshot")


def test_replay_detects_changed_behaviour_and_changed_spec():
    agent = spec()
    record = run_task(agent, count_handler, {"items": ["a"]}, action="read_snapshot")
    with pytest.raises(ReplayMismatch, match="output"):
        replay(agent, lambda i: {"count": 99}, record)
    with pytest.raises(ReplayMismatch, match="spec"):
        replay(spec(version="1.0.1"), count_handler, record)


def test_tampered_run_record_is_rejected():
    data = run_task(spec(), count_handler, {"items": ["a"]}, action="read_snapshot").to_dict()
    data["output"] = {"count": 5}
    with pytest.raises(ReplayMismatch):
        RunRecord.from_dict(data)

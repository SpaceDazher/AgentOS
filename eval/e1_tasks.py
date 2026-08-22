"""E1 evaluation tasks — the fixed sampling frame for the first measured run
(docs/EVALUATION_PROTOCOL.md). Each task is demo-class software work with
machine-checkable acceptance criteria executed by the deterministic harness.

Task ids are stable; do not reorder or edit existing entries (frame freeze).
"""
from __future__ import annotations

# Each task: key, concept, spec text, criteria (agentos acceptance_criteria
# dicts), plan (task list for Engine.plan_tasks), worker script (FakeWorker
# steps for harness-reliability drills; HermesAgentWorker ignores this).
E1_TASKS = [
    {
        "key": "greet-basic",
        "module": "greet.py",
        "concept": "Tiny greeting library: greet(name) -> 'hello, <name>', with unit tests.",
        "spec": "Module greet.py exposes greet(name)->str returning 'hello, <name>'. Include tests.",
        "criteria": [
            {"criterion_id": "has_code", "kind": "tests_present"},
            {"criterion_id": "runs", "kind": "command_exit_0",
             "params": {"entry": "greet.py", "call": "greet", "arg": "world",
                        "expect_stdout_contains": "hello, world"}},
        ],
        "plan": [{"key": "impl", "title": "Implement greet with tests",
                  "definition_of_done": "greet.py written via gateway; criteria pass"}],
        "script": [{"ok": True}],
    },
    {
        "key": "add-int",
        "module": "calc.py",
        "concept": "Arithmetic helper: add(a, b) -> a + b, with tests.",
        "spec": "Module calc.py exposes add(a,b)->int. Include tests.",
        "criteria": [
            {"criterion_id": "has_code", "kind": "tests_present"},
            {"criterion_id": "runs", "kind": "command_exit_0",
             "params": {"entry": "calc.py", "call": "add",
                        "arg": "[2, 1]",
                        "expect_stdout_contains": "3"}},
        ],
        "plan": [{"key": "impl", "title": "Implement add with tests",
                  "definition_of_done": "calc.py written via gateway; criteria pass"}],
        "script": [{"ok": True}],
    },
    {
        "key": "reverse-str",
        "module": "strutil.py",
        "concept": "String utility: reverse(s) -> reversed string, with tests.",
        "spec": "Module strutil.py exposes reverse(s)->str. Include tests.",
        "criteria": [
            {"criterion_id": "has_code", "kind": "tests_present"},
            {"criterion_id": "runs", "kind": "command_exit_0",
             "params": {"entry": "strutil.py", "call": "reverse", "arg": "abc",
                        "expect_stdout_contains": "cba"}},
        ],
        "plan": [{"key": "impl", "title": "Implement reverse with tests",
                  "definition_of_done": "strutil.py written via gateway"}],
        "script": [{"ok": True}],
    },
    {
        "key": "max-of-list",
        "module": "lists.py",
        "concept": "List utility: maximum(xs) -> largest element, with tests.",
        "spec": "Module lists.py exposes maximum(xs)->number (raises ValueError on empty). Include tests.",
        "criteria": [
            {"criterion_id": "has_code", "kind": "tests_present"},
            {"criterion_id": "runs", "kind": "command_exit_0",
             "params": {"entry": "lists.py", "call": "maximum",
                        "arg": "[[1, 9, 4]]",
                        "expect_stdout_contains": "9"}},
        ],
        "plan": [{"key": "impl", "title": "Implement maximum with tests",
                  "definition_of_done": "lists.py written via gateway"}],
        "script": [{"ok": True}],
    },
    {
        "key": "flaky-recover",
        "module": "counter.py",
        "concept": "Counter module with tests; worker fails once then recovers (retry drill).",
        "spec": "Module counter.py exposes bump(n)->n+1. Include tests.",
        "criteria": [
            {"criterion_id": "has_code", "kind": "tests_present"},
            {"criterion_id": "no_bad_rows", "kind": "invariant",
             "params": {"sql": "SELECT id FROM task WHERE status='FAILED'",
                        "expect_rows": 0}},
        ],
        "plan": [{"key": "impl", "title": "Implement counter with tests",
                  "definition_of_done": "counter.py written via gateway"}],
        "script": [{"ok": False}, {"ok": True}],
    },
]

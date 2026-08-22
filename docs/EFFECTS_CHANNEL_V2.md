# Effects channel v2: length-prefixed blocks (robust against any content)

## Problem

v1 used one-line JSON: `AGENTOS_EFFECTS {"path": ..., "content": "..."}`.
Models emit raw newlines and unescaped quotes inside `content` (docstrings!),
which makes strict JSON parsing impossible to recover reliably.

## v2 format (adopted)

    AGENTOS_EFFECTS_BEGIN <path>
    <raw file content, verbatim, any bytes except the exact end marker below>
    AGENTOS_EFFECTS_END <path>

- Path appears twice; both must match and be workspace-confined.
- Content is raw — no escaping needed at all. The only constraint is that the
  content must not contain a line equal to `AGENTOS_EFFECTS_END <path>`.
- The final line remains `AGENTOS_RESULT {...}` (single-line JSON, tiny).

v1 lines are still accepted for backward compatibility, but v2 takes priority
when present. The prompt now instructs models to use v2 exclusively.

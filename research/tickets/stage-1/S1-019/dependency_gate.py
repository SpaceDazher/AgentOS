"""Availability precheck only: presence never proves canonical evidence."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess

PINNED_COMMIT = '26f360bb4045e14c1b2cd4d36596d8b5eceea60d'


class GateInputError(ValueError):
    pass


class StrictJsonError(GateInputError):
    pass


class PathSafetyError(GateInputError):
    pass


def load_strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise StrictJsonError('duplicate JSON key: ' + key)
            result[key] = value
        return result

    def constant(value):
        raise StrictJsonError('non-finite JSON: ' + value)

    try:
        result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError) as exc:
        raise StrictJsonError(str(exc)) from exc
    if not isinstance(result, dict):
        raise StrictJsonError('record must be an object')
    return result


def validate_repo_relative_path(value):
    if (not value or '\\' in value or ':' in value or '\x00' in value
            or PurePosixPath(value).is_absolute()
            or any(p in ('', '.', '..') for p in value.split('/'))):
        raise PathSafetyError('unsafe Git path')
    return value


def _git(repo, *args):
    p = subprocess.run(['git', '-C', str(repo), *args], capture_output=True)
    if p.returncode:
        raise GateInputError(p.stderr.decode('utf-8', errors='replace').strip())
    return p.stdout


def resolve_pinned_commit(repo, ref):
    if not re.fullmatch('[0-9a-f]{40}', ref):
        raise GateInputError('full immutable commit SHA required')
    if _git(repo, 'rev-parse', '--verify', ref + '^{commit}').decode().strip() != ref:
        raise GateInputError('commit did not resolve exactly')
    return ref


def read_regular_blob(repo, commit, path):
    validate_repo_relative_path(path)
    entry = _git(repo, 'ls-tree', '-z', commit, '--', path)
    if not entry:
        return None
    parts = entry.rstrip(b'\x00').split(b'\t')
    if len(parts) != 2 or parts[1].decode() != path:
        raise GateInputError('unexpected tree entry')
    mode, kind, oid = parts[0].split()
    if mode not in (b'100644', b'100755') or kind != b'blob':
        raise GateInputError('regular Git blob required, not a link/tree')
    return _git(repo, 'cat-file', 'blob', oid.decode())


def run_gate(repo, ref):
    commit = resolve_pinned_commit(repo, ref)
    rows = []
    for n in range(1, 19):
        ticket = f'S1-{n:03d}'
        prefix = f'research/tickets/stage-1/{ticket}/'
        row = dict(ticket=ticket, path=prefix + 'evaluation-record.json',
                   problems=[], status='CANONICAL_VERIFICATION_REQUIRED')
        try:
            raw = read_regular_blob(repo, commit, row['path'])
            if raw is None:
                candidate = read_regular_blob(repo, commit, prefix + 'candidate-record.json')
                row['problems'].append('missing evaluation-record.json; ' +
                    ('candidate-record.json is not a substitute' if candidate is not None
                     else 'candidate-record.json also absent'))
            else:
                load_strict_json(raw)
                row['record_file_sha256'] = hashlib.sha256(raw).hexdigest()
        except GateInputError as exc:
            row['problems'].append(str(exc))
        if row['problems']:
            row['status'] = 'BLOCKED_DEPENDENCY'
        rows.append(row)
    return dict(schema='agentos.s1-019.dependency-availability/v1', commit=commit,
                synthesis_authorized=False,
                status='BLOCKED_DEPENDENCY' if any(r['problems'] for r in rows)
                else 'CANONICAL_VERIFICATION_REQUIRED',
                verification_scope='record availability and strict JSON only; not pack/identity/chain proof',
                dependencies=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path('.'))
    parser.add_argument('--ref', default=PINNED_COMMIT)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    try:
        report = run_gate(args.repo, args.ref)
    except GateInputError as exc:
        report = dict(status='BLOCKED_DEPENDENCY', synthesis_authorized=False, error=str(exc))
    encoded = json.dumps(report, indent=2, sort_keys=True) + '\n'
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(encoded, encoding='utf-8', newline='\n')
    print(encoded, end='')
    return 2  # Availability alone never grants PASS.


if __name__ == '__main__':
    raise SystemExit(main())

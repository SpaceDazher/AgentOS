"""Publish S1-014 from read-only canonical DB; approval binds INPUT, not output.

The approved preparation bundle and recorded operator decision are immutable
Git inputs. Frozen make_bundle.py must reproduce both preparation and closure.
No answer is rewritten to hide the expected input/output digest difference.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import importlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[3]
APPROVED_REF = 'b5890dc6aa22e348692d9c2889dec32b87bbd146'
OPERATOR_REF = 'f24488af89bb67c2fae8be0d82049d61c4b6e188'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate JSON key: ' + key)
            result[key] = value
        return result

    def bad(value):
        raise ValueError('nonfinite JSON: ' + value)

    result = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=bad)
    if not isinstance(result, dict):
        raise ValueError('JSON object required')
    return result


@contextmanager
def ticket_modules(here):
    names = ('contract', 'evaluator', 'importer', 'publisher', 'make_bundle', 'dependency_gate')
    saved = {name: sys.modules.get(name) for name in names}
    old_path = sys.path[:]
    try:
        for name in names:
            sys.modules.pop(name, None)
        sys.path.insert(0, str(here))
        yield {name: importlib.import_module(name) for name in names}
    finally:
        sys.path[:] = old_path
        for name, module in saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def git_blob(repo, commit, path):
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('immutable full commit required')
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args])
    entry = git('ls-tree', '-z', commit, '--', path)
    parts = entry.rstrip(b'\0').split(b'\t')
    if len(parts) != 2 or parts[1].decode() != path:
        raise ValueError('missing or ambiguous historical input')
    mode, kind, oid = parts[0].split()
    if mode not in (b'100644', b'100755') or kind != b'blob':
        raise ValueError('historical input is not a regular blob')
    return git('cat-file', 'blob', oid.decode())


def verify_approval(here, modules, *, bundle_override=None, decision_override=None):
    c, publisher, builder = (modules[n] for n in ('contract', 'publisher', 'make_bundle'))
    problems = publisher.check_frozen(here)
    if problems:
        raise ValueError('frozen inputs changed: ' + '; '.join(problems))
    load = lambda name: strict_json((here / name).read_bytes())
    candidate, frozen = load('candidate-record.json'), load('frozen-manifest.json')
    bundle = load('bundle.json') if bundle_override is None else bundle_override
    decision = load('operator-decision.json') if decision_override is None else decision_override
    rel = here.relative_to(here.parents[3]).as_posix()
    approved_raw = git_blob(here.parents[3], APPROVED_REF, rel + '/bundle.json')
    operator_raw = git_blob(here.parents[3], OPERATOR_REF, rel + '/operator-decision.json')
    if decision != strict_json(operator_raw):
        raise ValueError('operator answer differs from recorded approval')
    problems = publisher.verify_decision(decision, frozen, sha(approved_raw))
    if problems:
        raise ValueError('approval rejected: ' + '; '.join(problems))
    expected_decision = dict(outcome=publisher.decision_outcome(decision['selected_answers']),
                             selected_answers=decision['selected_answers'],
                             decided_at_utc=decision['decided_at_utc'], operator_id=decision['operator_id'])
    if (candidate.get('status') != 'PASS_WITH_LIMITS'
            or candidate.get('operator_review') != 'RECORDED'
            or type(candidate.get('operator_review_n')) is not int or candidate['operator_review_n'] != 1
            or type(candidate.get('human_study_n')) is not int or candidate['human_study_n'] != 0
            or candidate.get('comparative_human_effectiveness') != 'NOT_MEASURED'
            or candidate.get('winner') is not None
            or candidate.get('provisional_design_decision') != expected_decision
            or candidate.get('frozen_manifest_sha256') != frozen['manifest_sha256']
            or candidate.get('browser_contract_sha256') != frozen['browser_contract_sha256']):
        raise ValueError('candidate closure or approval binding mismatch')
    metrics, probes, comparison, gate = (load('results/' + n + '.json')
                                        for n in ('metrics','probes','comparison','dependency-gate'))
    prepared = copy.deepcopy(candidate)
    prepared.update(status='PREPARATION_READY', provisional_design_decision=None, operator_review_n=0)
    if builder.build(prepared, metrics, probes, comparison, gate) != strict_json(approved_raw):
        raise ValueError('approved preparation bundle not reproducible')
    if builder.build(candidate, metrics, probes, comparison, gate) != bundle:
        raise ValueError('closure bundle not derived from frozen builder and approved answers')
    current_sha = sha((here / 'bundle.json').read_bytes())
    if candidate.get('bundle_sha256') != current_sha:
        raise ValueError('candidate bundle digest is stale')
    return dict(approved_ref=APPROVED_REF, operator_ref=OPERATOR_REF,
                approved_bundle_sha256=sha(approved_raw), current_bundle_sha256=current_sha,
                operator_decision_sha256=sha(operator_raw), approved_input=approved_raw)


def verify_binding(series, evaluation, pack, current_chain):
    r = pack.get('research', {})
    chain = evaluation.get('artifact_chain_hash')
    latest = max(r.get('evaluations', []), key=lambda e: (e.get('evaluation_version', 0),e.get('id','')), default={})
    if not all((series.get('research_key') == 'S1-014',
                evaluation.get('result') == 'pass_with_limits',
                bool(re.fullmatch(r'[0-9a-f]{64}', chain or '')),
                chain == current_chain == r.get('current_chain_hash') == r.get('latest_chain_hash'),
                series.get('goal_id') == evaluation.get('goal_id') == pack.get('goal',{}).get('id'),
                series.get('campaign_id') == evaluation.get('campaign_id') == r.get('campaign',{}).get('id'),
                r.get('chain_fresh') is True, r.get('latest_evaluation_valid') is True,
                latest.get('id') == evaluation.get('id'),
                latest.get('goal_id') == evaluation.get('goal_id'),
                latest.get('campaign_id') == evaluation.get('campaign_id'),
                latest.get('result') == evaluation.get('result'),
                latest.get('artifact_chain_hash') == chain)):
        raise ValueError('stale or mismatched canonical binding')


def read_chain_payload(conn, goal_id, db_root):
    """Portable snapshot of the exact research._chain_hash input, plus bodies."""
    def rows(sql):
        return [dict(r) for r in conn.execute(sql, (goal_id,))]
    campaign = rows('SELECT id,goal_id,topic,config_json,thresholds_json,manifest_sha256 FROM research_campaign WHERE goal_id=?')[0]
    sources = rows('SELECT id,goal_id,canonical_uri,title,source_type,content_sha256,verification_status,verifier,verification_method,verifier_provenance_json FROM research_source WHERE goal_id=? ORDER BY id')
    claims = rows('SELECT id,goal_id,text,claim_class FROM research_claim WHERE goal_id=? ORDER BY id')
    links = rows('SELECT claim_id,source_id,goal_id,relation FROM research_claim_source WHERE goal_id=? ORDER BY claim_id,source_id')
    artifacts = rows('SELECT id,goal_id,kind,artifact_name,version,content_sha256,storage_path,claim_refs_json,producer FROM research_artifact WHERE goal_id=? ORDER BY kind,version,id')
    artifact_links = rows('SELECT artifact_id,claim_id,goal_id FROM research_artifact_claim WHERE goal_id=? ORDER BY artifact_id,claim_id')
    bodies = {}
    allowed = (db_root / 'goals' / goal_id / 'research').resolve()
    for a in artifacts:
        path = Path(a['storage_path'])
        if path.is_symlink() or not path.resolve().is_relative_to(allowed):
            raise ValueError('canonical artifact path escapes goal research scope')
        raw = path.read_bytes()
        if sha(raw) != a['content_sha256']:
            raise ValueError('canonical artifact body changed')
        a.update(host_file_exists=True, host_file_sha256=sha(raw))
        bodies[a['id']] = dict(content=raw.decode('utf-8'), sha256=sha(raw))
    return dict(campaign=campaign,sources=sources,claims=claims,claim_sources=links,
                artifacts=artifacts,artifact_claims=artifact_links), bodies


def verify_dependency_databases(expected, roots, chain_fn):
    proofs=[]
    for ticket, binding in expected.items():
        proof=None
        for root in roots:
            db_file=root/'agentos.db'
            if not db_file.is_file():
                continue
            with sqlite3.connect(db_file.as_uri()+'?mode=ro',uri=True) as conn:
                conn.row_factory=sqlite3.Row
                conn.execute('BEGIN')
                row=conn.execute('SELECT * FROM research_evaluation WHERE goal_id=? ORDER BY evaluation_version DESC,id DESC LIMIT 1',(binding['goal_id'],)).fetchone()
                if row is None:
                    continue
                if (row['id']!=binding['evaluation_id'] or row['campaign_id']!=binding['campaign_id']
                        or row['artifact_chain_hash']!=binding['artifact_chain_hash']
                        or row['result']!='pass_with_limits'
                        or chain_fn(SimpleNamespace(conn=conn),binding['goal_id'])!=binding['artifact_chain_hash']):
                    raise ValueError('canonical dependency DB binding is stale: '+ticket)
                proof=dict(ticket_id=ticket,goal_id=row['goal_id'],campaign_id=row['campaign_id'],
                           evaluation_id=row['id'],artifact_chain_hash=row['artifact_chain_hash'],
                           result=row['result'],chain_recomputed_from_disk=True)
                break
        if proof is None:
            raise ValueError('canonical dependency DB unavailable: '+ticket)
        proofs.append(proof)
    return proofs


def publication(db_root, check_only=False, dependency_roots=()):
    sys.path.insert(0, str(REPO / 'src'))
    from agentos.research import _manifest_hash, _normalise_config, research_chain_hash
    from agentos.evidence_pack import build
    with ticket_modules(HERE) as modules:
        proof = verify_approval(HERE,modules)
        publisher = modules['publisher']
        deps = modules['dependency_gate'].run()
        if not deps['operator_review_dependencies_proven']:
            raise ValueError('dependency gate failed')
        canonical_deps=verify_dependency_databases(modules['dependency_gate'].EXPECTED,
                            [db_root,*dependency_roots],research_chain_hash)
        with tempfile.TemporaryDirectory(prefix='s1014-publication-replay-') as td:
            replay = publisher.replicate(Path(td)/'replay')
            probes = publisher.run_probes(Path(td)/'probes')
        saved = strict_json((HERE/'results/metrics.json').read_bytes())
        semantic = lambda d: {k:v for k,v in d.items() if k not in ('executor','nonce','pid')}
        if (semantic(saved) != semantic(replay['metrics']) or not replay['replicated']
                or not replay['metrics']['hard_gates_green'] or not probes['all_detected']):
            raise ValueError('fresh replay/probes do not support recorded evidence')
    with sqlite3.connect((db_root/'agentos.db').as_uri()+'?mode=ro', uri=True) as conn:
        conn.row_factory=sqlite3.Row
        conn.execute('BEGIN')
        s=conn.execute("SELECT * FROM research_series WHERE research_key=? ORDER BY revision DESC LIMIT 1",('S1-014',)).fetchone()
        if s is None:
            raise ValueError('canonical S1-014 series missing')
        series=dict(s)
        e=conn.execute('SELECT * FROM research_evaluation WHERE goal_id=? ORDER BY evaluation_version DESC,id DESC LIMIT 1',(series['goal_id'],)).fetchone()
        if e is None:
            raise ValueError('canonical evaluation missing')
        evaluation=dict(e)
        bundle=strict_json((HERE/'bundle.json').read_bytes())
        config,errors=_normalise_config(None,bundle)
        manifest,more_errors=_manifest_hash(bundle,config)
        if errors or more_errors or manifest != series['manifest_sha256']:
            raise ValueError('bundle is not the canonical revision input')
        db=SimpleNamespace(conn=conn)
        current_chain=research_chain_hash(db,series['goal_id'])
        pack_raw=(db_root/'goals'/series['goal_id']/'evidence-pack.json').read_bytes()
        pack=strict_json(pack_raw)
        if sha(canonical({k:v for k,v in pack.items() if k!='sha256'})) != pack.get('sha256'):
            raise ValueError('canonical pack self-hash mismatch')
        verify_binding(series,evaluation,pack,current_chain)
        with tempfile.TemporaryDirectory(prefix='s1014-db-pack-check-') as td:
            fresh=build(db,td,series['goal_id'])['pack']
        if pack['research'] != fresh['research']:
            raise ValueError('pack research rows differ from canonical DB')
        chain_payload,bodies=read_chain_payload(conn,series['goal_id'],db_root)
        if sha(canonical(chain_payload)) != current_chain:
            raise ValueError('portable chain snapshot does not reproduce canonical chain')
    approved_raw=proof.pop('approved_input')
    evidence_dir=HERE/'results/evidence'
    def artifact(raw,prefix):
        path=evidence_dir/f'{prefix}-{sha(raw)}.json'
        return dict(path=path.relative_to(REPO).as_posix(),sha256=sha(raw)),(path,raw)
    pack_ref,pack_file=artifact(pack_raw,'evidence-pack')
    approved_ref,approved_file=artifact(approved_raw,'approved-bundle')
    pack_ref.update(payload_sha256=pack['sha256'],chain_fresh=True,latest_evaluation_valid=True)
    paths=[p for p in HERE.rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and 'evidence' not in p.relative_to(HERE).parts and p.name!='evaluation-record.json']
    paths+=list((REPO/'tests').glob('test_s1_014*.py'))
    if any(p.is_symlink() for p in paths):
        raise ValueError('tracked evidence includes symlink')
    hashes={p.relative_to(REPO).as_posix():sha(p.read_bytes()) for p in sorted(paths)}
    payload=dict(schema='agentos.s1-014.ticket-evidence/v1',ticket_id='S1-014',
                 series=series,evaluation=evaluation,canonical_pack=pack_ref,
                 approval={**proof,'approved_input':approved_ref},
                 canonical_chain_payload=chain_payload,canonical_artifact_bodies=bodies,
                 dependencies=deps,canonical_dependencies=canonical_deps,
                 verified_replay={k:v for k,v in replay.items() if k!='metrics'},
                 verified_probes=probes,tracked_artifact_hashes=hashes)
    digest=sha(canonical(payload))
    ticket_ref,ticket_file=artifact(canonical(dict(payload=payload,payload_sha256=digest))+b'\n','ticket-pack')
    ticket_ref['payload_sha256']=digest
    record=dict(schema='agentos.ticket-evaluation-record/v2',ticket_id='S1-014',
                research_revision=series['revision'],goal_id=series['goal_id'],campaign_id=series['campaign_id'],
                evaluation_id=evaluation['id'],result=evaluation['result'],artifact_chain_hash=current_chain,
                manifest_sha256=manifest,bundle_sha256=proof['current_bundle_sha256'],
                evidence_pack=pack_ref,ticket_pack=ticket_ref,approval=payload['approval'],
                canonical_dependencies=canonical_deps,
                operator_review_n=1,human_study_n=0,comparative_human_effectiveness='NOT_MEASURED',
                provisional_design_decision='CARD_WITH_GRAPH_DRILLDOWN',winner=None,
                limitations=json.loads(evaluation['limitations_json']),tracked_artifact_hashes=hashes)
    if not check_only:
        evidence_dir.mkdir(parents=True,exist_ok=True)
        for path,raw in (pack_file,approved_file,ticket_file):
            if path.exists() and path.read_bytes()!=raw:
                raise ValueError('content-address collision')
            path.write_bytes(raw)
        (HERE/'evaluation-record.json').write_bytes(json.dumps(record,indent=2,sort_keys=True,ensure_ascii=False).encode()+b'\n')
    return record


def verify_tracked(repo=REPO):
    """Offline verification from clone/archive bytes; no local DB needed."""
    here=repo/'research/tickets/stage-1/S1-014'
    record=strict_json((here/'evaluation-record.json').read_bytes())
    def raw_file(rel,expected):
        if (not isinstance(rel,str) or '\\' in rel or ':' in rel
                or any(p in ('','.','..') for p in rel.split('/'))
                or not rel.startswith(('research/tickets/stage-1/S1-014/','tests/test_s1_014'))):
            raise ValueError('unsafe tracked artifact path')
        path=repo/rel
        if path.is_symlink() or not path.resolve().is_relative_to(repo.resolve()):
            raise ValueError('tracked artifact escapes repository')
        raw=path.read_bytes()
        if not re.fullmatch('[0-9a-f]{64}',expected or '') or sha(raw)!=expected:
            raise ValueError('tracked artifact hash mismatch: '+rel)
        return raw
    def ref_file(ref):
        raw=raw_file(ref['path'],ref['sha256'])
        if not Path(ref['path']).name.endswith('-'+ref['sha256']+'.json'):
            raise ValueError('content-addressed filename mismatch')
        return strict_json(raw)
    pack=ref_file(record['evidence_pack'])
    if sha(canonical({k:v for k,v in pack.items() if k!='sha256'})) != pack.get('sha256'):
        raise ValueError('pack self-hash mismatch')
    if record['evidence_pack']['payload_sha256']!=pack['sha256']:
        raise ValueError('pack payload binding mismatch')
    ticket=ref_file(record['ticket_pack']); payload=ticket['payload']
    if sha(canonical(payload))!=ticket.get('payload_sha256') or ticket['payload_sha256']!=record['ticket_pack']['payload_sha256']:
        raise ValueError('ticket payload hash mismatch')
    if (payload['canonical_pack']!=record['evidence_pack'] or payload['approval']!=record['approval']
            or payload['canonical_dependencies']!=record['canonical_dependencies']):
        raise ValueError('record differs from ticket pack references')
    approved=ref_file(record['approval']['approved_input'])
    chain=sha(canonical(payload['canonical_chain_payload']))
    verify_binding(payload['series'],payload['evaluation'],pack,chain)
    for key in ('goal_id','campaign_id','result','artifact_chain_hash'):
        if record[key]!=payload['evaluation'][key]:
            raise ValueError('record evaluation binding mismatch: '+key)
    if (record['evaluation_id']!=payload['evaluation']['id']
            or record['research_revision']!=payload['series']['revision']
            or record['manifest_sha256']!=payload['series']['manifest_sha256']
            or record['artifact_chain_hash']!=chain
            or record['tracked_artifact_hashes']!=payload['tracked_artifact_hashes']):
        raise ValueError('record revision/hash binding mismatch')
    for rel,digest in record['tracked_artifact_hashes'].items():
        raw_file(rel,digest)
    for a in payload['canonical_chain_payload']['artifacts']:
        body=payload['canonical_artifact_bodies'][a['id']]
        digest=sha(body['content'].encode('utf-8'))
        if digest!=body['sha256'] or digest!=a['content_sha256'] or digest!=a['host_file_sha256'] or a['host_file_exists'] is not True:
            raise ValueError('portable artifact body mismatch')
    candidate=strict_json((here/'candidate-record.json').read_bytes())
    if (record['human_study_n']!=0 or record['operator_review_n']!=1
            or record['comparative_human_effectiveness']!='NOT_MEASURED'
            or record['limitations']!=json.loads(payload['evaluation']['limitations_json'])
            or record['provisional_design_decision']!=candidate['provisional_design_decision']['outcome']
            or record['winner'] is not None or approved['s1_014']['status']!='PREPARATION_READY'):
        raise ValueError('closure limitations changed')
    return dict(status='PROVEN',ticket_id='S1-014',goal_id=record['goal_id'],
                evaluation_id=record['evaluation_id'],artifact_chain_hash=chain,
                tracked_hashes=len(record['tracked_artifact_hashes']))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--verify-tracked',action='store_true')
    parser.add_argument('--dependency-db',type=Path,action='append',default=[])
    args=parser.parse_args()
    try:
        if args.verify_tracked:
            record=verify_tracked()
        else:
            if args.db is None:
                parser.error('--db is required for canonical publication')
            record=publication(args.db.resolve(),args.check_only,
                               [p.resolve() for p in args.dependency_db])
    except (ValueError,OSError,sqlite3.Error,subprocess.SubprocessError) as exc:
        print('publication blocked: '+str(exc),file=sys.stderr)
        return 1
    print(json.dumps({k:v for k,v in record.items() if k!='tracked_artifact_hashes'},ensure_ascii=False))
    return 0


if __name__=='__main__':
    raise SystemExit(main())

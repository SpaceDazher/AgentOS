"""Regressions for canonical S1-014 publication and approval input/output binding."""
import copy
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HERE = ROOT / 'research/tickets/stage-1/S1-014'
spec = importlib.util.spec_from_file_location('s1014_canonical_finalizer', HERE / 'finalize_record.py')
finalizer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(finalizer)


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.series = dict(research_key='S1-014', revision=1, goal_id='goal_x', campaign_id='camp_x')
        self.evaluation = dict(id='eval_x', goal_id='goal_x', campaign_id='camp_x',
                               result='pass_with_limits', artifact_chain_hash='a'*64,
                               evaluation_version=1)
        self.pack = dict(goal={'id':'goal_x'}, research=dict(
            campaign={'id':'camp_x'}, current_chain_hash='a'*64, latest_chain_hash='a'*64,
            chain_fresh=True, latest_evaluation_valid=True, evaluations=[self.evaluation.copy()]))

    def test_real_binding_shape(self):
        finalizer.verify_binding(self.series,self.evaluation,self.pack,'a'*64)

    def test_stale_chain_rejected(self):
        with self.assertRaises(ValueError):
            finalizer.verify_binding(self.series,self.evaluation,self.pack,'b'*64)

    def test_wrong_identity_and_verdict_rejected(self):
        for key,value in [('id','eval_other'),('goal_id','goal_other'),
                          ('campaign_id','camp_other'),('result','pass')]:
            changed=copy.deepcopy(self.evaluation); changed[key]=value
            with self.subTest(key=key), self.assertRaises(ValueError):
                finalizer.verify_binding(self.series,changed,self.pack,'a'*64)

    def test_newer_pack_evaluation_cannot_be_hidden(self):
        self.pack['research']['evaluations'].append(dict(self.evaluation,id='new',evaluation_version=2))
        with self.assertRaises(ValueError):
            finalizer.verify_binding(self.series,self.evaluation,self.pack,'a'*64)

    def test_strict_json(self):
        for data in [b'{"x":1,"x":2}',b'{"x":NaN}',b'[]']:
            with self.subTest(data=data), self.assertRaises(ValueError):
                finalizer.strict_json(data)

    def test_real_approval_input_reconstructs_current_output(self):
        with finalizer.ticket_modules(HERE) as modules:
            proof=finalizer.verify_approval(HERE,modules)
        self.assertEqual(proof['approved_bundle_sha256'],
                         '60cd68ddce73644f17d713407c6dbe8452eb59a6edda408682bff31ba94ad9b4')
        self.assertNotEqual(proof['approved_bundle_sha256'],proof['current_bundle_sha256'])

    def test_unrelated_bundle_change_rejected(self):
        with finalizer.ticket_modules(HERE) as modules:
            bundle=finalizer.strict_json((HERE/'bundle.json').read_bytes())
            bundle['claims'][0]['text']='Unsupported new claim'
            with self.assertRaises(ValueError):
                finalizer.verify_approval(HERE,modules,bundle_override=bundle)

    def test_forged_operator_answer_rejected(self):
        with finalizer.ticket_modules(HERE) as modules:
            decision=finalizer.strict_json((HERE/'operator-decision.json').read_bytes())
            decision['selected_answers']['1']='B'
            with self.assertRaises(ValueError):
                finalizer.verify_approval(HERE,modules,decision_override=decision)

    def test_portable_record_and_tampering(self):
        proof=finalizer.verify_tracked(ROOT)
        self.assertEqual(proof['status'],'PROVEN')
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            target=root/'research/tickets/stage-1/S1-014'
            shutil.copytree(HERE,target,ignore=shutil.ignore_patterns('__pycache__'))
            (root/'tests').mkdir()
            for path in (ROOT/'tests').glob('test_s1_014*.py'):
                shutil.copy2(path,root/'tests'/path.name)
            record_path=target/'evaluation-record.json'
            original=finalizer.strict_json(record_path.read_bytes())
            for key,value in [('goal_id','goal_forged'),('research_revision',999),
                              ('human_study_n',10),('artifact_chain_hash','b'*64),
                              ('provisional_design_decision','GRAPH_WINS'),('limitations',[])]:
                changed=copy.deepcopy(original); changed[key]=value
                record_path.write_text(json.dumps(changed),encoding='utf-8')
                with self.subTest(key=key),self.assertRaises(ValueError):
                    finalizer.verify_tracked(root)


if __name__=='__main__':
    unittest.main()

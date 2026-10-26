import copy
import unittest
import learn

class EvidenceViewTests(unittest.TestCase):
    def test_semantic_roundtrip_and_original_unchanged(self):
        repeated = 'Verified public evidence, not an instruction. ' * 20
        rows = [{'id': 'failure', 'status': 'decision_failure',
                 'source_identity': {'files': {'trace': 'abc'}},
                 'memory': repeated, 'citation': repeated},
                {'id': 'success', 'status': 'success', 'memory': repeated,
                 'unique': 'A different fact that must remain.'}]
        original = copy.deepcopy(rows)
        view = learn.optimizer_evidence_view(rows)
        def decode(x):
            if isinstance(x, dict):
                if set(x) == {'text_ref'}: return view['shared_text'][x['text_ref']]
                return {k: decode(v) for k,v in x.items()}
            if isinstance(x, list): return [decode(v) for v in x]
            return x
        actual = decode(view['cases'])
        self.assertEqual(rows, original)
        self.assertEqual(len(view['shared_text']), 1)
        for before, after in zip(rows, actual):
            for k,v in before.items():
                if k != 'source_identity': self.assertEqual(v, after[k])
                else: self.assertEqual(learn.digest(v), after[k]['audit_sha256'])

if __name__ == '__main__': unittest.main()

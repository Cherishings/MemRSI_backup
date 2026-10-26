import copy
import unittest
from memory_policy import BASE, EMPTY, archive_request, combinations, choose_smallest, operator_credit, screen


class Tests(unittest.TestCase):
    def test_component_interventions_are_isolated(self):
        candidate = dict(BASE, update='NEW_UPDATE', guidance='NEW_GUIDANCE')
        variants = combinations(BASE, candidate)
        self.assertEqual(variants['update_only']['guidance'], BASE['guidance'])
        self.assertEqual(variants['guidance_only']['update'], BASE['update'])

    def test_archive_preserves_observations_and_tools(self):
        req = {'messages': [{'role': 'system', 'content': 'archive'}, {'role': 'user', 'content': 'actual feedback'}],
               'tools': [{'function': {'name': 'save_memory'}}]}
        old = copy.deepcopy(req)
        out = archive_request(req, BASE)
        self.assertEqual(req, old)
        self.assertEqual(out['messages'][1], req['messages'][1])
        self.assertEqual(out['tools'], req['tools'])
        self.assertIs(archive_request(req, EMPTY), req)

    def test_rejects_tradeoff_that_hides_regression(self):
        scores = {k: {'passed': v, 'tokens': 100} for k, v in {
            'old': [True, False, False], 'update_only': [False, True, True],
            'guidance_only': [True, False, False], 'joint': [True, True, False]}.items()}
        self.assertEqual(choose_smallest(scores), 'joint')

    def test_unchanged_or_all_pass_does_not_count_as_evolution(self):
        scores = {k: {'passed': [True, True], 'tokens': 100} for k in ('old','update_only','guidance_only','joint')}
        self.assertEqual(choose_smallest(scores), 'old')
        self.assertEqual(operator_credit(scores)['interaction'], 0)

    def test_answer_specific_policy_rejected(self):
        with self.assertRaises(ValueError):
            screen(dict(BASE, guidance='Always call serve_table_one.'))
        self.assertTrue(screen(BASE))

if __name__ == '__main__':
    unittest.main()

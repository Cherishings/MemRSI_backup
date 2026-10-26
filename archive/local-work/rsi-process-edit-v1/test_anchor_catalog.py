import unittest
from anchor_catalog import schema_for
import learn
class AnchorTests(unittest.TestCase):
    def test_exact_unique_and_bounded(self):
        parent={'guidance':'First unique sentence. Repeated. Repeated. Last unique sentence.','update':'Alpha. Beta. Gamma. Delta.'}
        schema=schema_for(parent,learn.JOINT_SCHEMA)
        for target in parent:
            values=schema['properties'][target+'_anchor']['enum']
            self.assertEqual(values[0],'')
            for anchor in values[1:]:
                self.assertEqual(parent[target].count(anchor),1)
                self.assertLessEqual(len(anchor),min(450,int(len(parent[target])*.35)))
        self.assertNotIn('Repeated.',schema['properties']['guidance_anchor']['enum'])
    def test_omitted_middle_sentence_rejected(self):
        p={'guidance':'One. Middle. Last. '+'Other text. '*20,'update':'Other. '*20}
        s=schema_for(p,learn.JOINT_SCHEMA)
        self.assertNotIn('One. Last.',s['properties']['guidance_anchor']['enum'])
        self.assertIn('One.',s['properties']['guidance_anchor']['enum'])
    def test_original_schema_unchanged_and_empty_allowed(self):
        s=schema_for({'guidance':'a. b. c.','update':'d. e. f.'},learn.JOINT_SCHEMA)
        self.assertNotIn('enum',learn.JOINT_SCHEMA['properties']['guidance_anchor'])
        self.assertIn('',s['properties']['update_anchor']['enum'])

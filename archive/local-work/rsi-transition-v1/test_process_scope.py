import unittest
from process_scope import validate
class ScopeTests(unittest.TestCase):
 def patch(self,text):return {'guidance_replacement':text,'update_replacement':'Retain unresolved obligations and their source.'}
 def test_process_text_allowed(self):validate(self.patch('Distinguish source containers from labels within evidence. Correlate receipts before concluding completion.'))
 def test_protocol_identifiers_rejected(self):
  for text in ['Set basis_ids to memory.','Call report_advice.','Change the tool schema.']:
   with self.assertRaises(ValueError):validate(self.patch(text))
 def test_numeric_protocol_limits_rejected(self):
  for text in ['Use at most 80 words.','Allow 1200 characters.','Use 8192 tokens.']:
   with self.assertRaises(ValueError):validate(self.patch(text))

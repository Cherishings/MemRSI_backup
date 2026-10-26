import unittest,queue
from types import SimpleNamespace
from collections import deque
import numpy as np
from history_controller import replace_conditioning,history_signature,BoundaryError

class Decoder:
    def __init__(self):self.action_queue=queue.Queue();self.action_queue.put('future')
    def reset(self):self.action_queue=queue.Queue()

def example(calls=32):
    return SimpleNamespace(action_calls=calls,downsample_obs=8,start_pos=0,first_obs=False,
        last_observation={'rgb':np.arange(12).reshape(2,2,3)},last_action=np.ones((4,12)),
        seq_history={'action':np.zeros((3,12))},action_queue=deque(['future']),
        prism_action_decoder=Decoder(),language_embedding='old')

class HistoryTests(unittest.TestCase):
    def test_changes_language_and_only_unexecuted_actions(self):
        m=example();before=history_signature(m);new=np.ones((1,1,512))
        receipt=replace_conditioning(m,new)
        self.assertEqual(before,history_signature(m));self.assertIs(m.language_embedding,new)
        self.assertEqual(len(m.action_queue),0);self.assertTrue(m.prism_action_decoder.action_queue.empty())
        self.assertEqual(receipt['dropped_unexecuted_decoder'],1)
    def test_mid_sample_rejected_without_any_mutation(self):
        m=example(33);before=history_signature(m)
        with self.assertRaises(BoundaryError):replace_conditioning(m,'new')
        self.assertEqual(m.language_embedding,'old');self.assertEqual(before,history_signature(m));self.assertEqual(len(m.action_queue),1)
    def test_history_is_not_replaced_by_a_new_empty_sequence(self):
        m=example();old=(m.last_observation,m.last_action,m.seq_history)
        replace_conditioning(m,'new')
        for a,b in zip(old,(m.last_observation,m.last_action,m.seq_history)):self.assertIs(a,b)
if __name__=='__main__':unittest.main()

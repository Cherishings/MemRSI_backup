import unittest
import numpy as np
from adapters import public_casa,public_twin,checked_action,PolicyProtocolError
from catalog import TASKS

class Contract(unittest.TestCase):
    def test_bad_policy_actions_are_not_infrastructure_failures(self):
        for action in ([0,float('nan')],['not a number',0],[0]):
            with self.assertRaises(PolicyProtocolError):checked_action(action,2)
    def test_no_answer_leak_casa(self):
        raw={'robot0_agentview_left_image':np.zeros((4,4,3)), 'robot0_joint_pos':np.zeros(7),
             'object-state':np.ones(5),'fruit_container_pos':np.ones(3),
             'destination_container_name':'left','task_id':'MemWashAndReturnLeft'}
        self.assertEqual(set(public_casa(raw)),{'robot0_agentview_left_image','robot0_joint_pos'})
    def test_no_answer_leak_twin(self):
        raw={'observation':{'head':{'rgb':np.zeros((4,4,3)),'secret':1}},
             'joint_action':{'vector':np.zeros(14)},'endpose':{},'target_pose':[1,2,3],'mat_name':'left'}
        got=public_twin(raw);self.assertEqual(set(got),{'images','joint_action','endpose'})
        self.assertNotIn('secret',got['images'])
    def test_inventory(self):
        self.assertEqual(len(TASKS['rmbench']),9)
        self.assertEqual(len(TASKS['remembench']),13)
        for values in TASKS.values():self.assertEqual(len(values),len(set(values)))

if __name__=='__main__':unittest.main()

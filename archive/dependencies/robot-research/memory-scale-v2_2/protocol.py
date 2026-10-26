"""Private evaluator plan and public instruction protocol. No expected answer enters actor observations."""
BUDGET={'persistent_tokens':1024,'active_input_tokens':12288,'output_tokens_per_call':2048}

def contract(platform):
 ids=['station_A','station_C'] if platform=='twin' else ['station_A','station_C','station_D']
 detail=('station_A and station_C each stack two blocks using native gripper skills. A first invocation places the lower block and pauses; a second places the upper block, completing that station.' if platform=='twin' else 'Each station skill executes its assigned native counter-to-cabinet object placement using simulated gripper actions. Each station is a separate preserved kitchen scene.')
 text=('Use report_action with one skill and a short reason, then wait for physical feedback. '+detail+
 ' execute_current carries out the explicitly assigned temporary work order in a separate worksite. Each new work order has a new scene. The actor works serially at one site at a time; this benchmark routes between simulated sites, not real navigation. Returning to a station preserves its existing state. finish ends the workflow. Capabilities do not imply outstanding requests. Do not access other trials or write scripts.'+
 ' Only memory/MEMORY.md and memory/HISTORY.md are writable, together limited to 1024 tokens. Other trial logs are not available to the actor.')
 return text,ids+['execute_current','finish']

def case(platform,gap,reverse):
 targets=['station_A','station_C'] if platform=='twin' else ['station_C','station_D']
 if reverse:targets.reverse()
 seed_instruction=('Set up both stacking stations. First place only the lower block at station_A, then only the lower block at station_C, leaving both stations unfinished.' if platform=='twin' else 'Complete the three assigned kitchen storage jobs. Begin by completing station_A; station_C and station_D remain part of this same original mission.')
 initial=seed_instruction+f' After any temporary work is finished, complete the remaining original stations in this order: {targets[0]}, then {targets[1]}. Finish only after this mission is complete. Start station_A now.'
 steps=[dict(text=initial,expected='station_A',checkpoint=False)]
 if platform=='twin':steps.append(dict(text='Place only the lower block at station_C now, then pause that station.',expected='station_C',checkpoint=False,new_session=True))
 for i in range(gap):steps.append(dict(text=f'Temporary work order {i+1}: '+('move the can beside its pot' if platform=='twin' else 'put the assigned object from the counter into the cabinet')+'. Use execute_current for this work order.',expected='execute_current',checkpoint=False,new_session=True,work_order=i))
 for target in targets:steps.append(dict(text='Continue.',expected=target,checkpoint=True,new_session=True))
 steps.append(dict(text='Continue.',expected='finish',checkpoint=True,new_session=True))
 return dict(id=f'{platform}-gap{gap}-order{int(reverse)}',platform=platform,gap=gap,reverse=reverse,steps=steps,planned_checkpoints=3,planned_workflow_decisions=len(steps),physical_initializations_identical_across_orders=True)

def cases(platform):return [case(platform,gap,reverse) for gap in (4,8) for reverse in (False,True)]

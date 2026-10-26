"""End the actor iteration after a valid committed action, before physical feedback.

Preserves the native assistant/tool records and normal session persistence.
No action synthesis, argument repair, success check, or extra model request.
Both RMB arms install the same hook. The upstream package is never edited.
"""
import ast
import hashlib
import inspect
import textwrap
import types

UPSTREAM_SHA256 = '12cce013e27de995eeba05243bd7bd8ae417e6c29bbaa969c33e3c3085e98025'

def patch_loop(original, committed, audit):
    source = textwrap.dedent(inspect.getsource(original))
    if hashlib.sha256(source.encode()).hexdigest() != UPSTREAM_SHA256:
        raise RuntimeError('unrecognized_native_actor_loop')
    tree = ast.parse(source)
    fn = tree.body[0]
    branch = next(n for n in ast.walk(fn) if isinstance(n, ast.If)
                  and ast.unparse(n.test) == 'response.has_tool_calls')
    # All tool results from this response have already been recorded. A rejected
    # tool has no committed record, so the native retry/repair flow is retained.
    branch.body.extend(ast.parse(
        "if _committed():\n"
        "    _commit_audit(iteration, tools_used)\n"
        "    final_content = response.content or ''\n"
        "    break\n"
    ).body)
    ast.fix_missing_locations(tree)
    scope = dict(original.__globals__, _committed=committed, _commit_audit=audit)
    exec(compile(tree, '<audited_action_commit_boundary>', 'exec'), scope)
    return scope[original.__name__]

def install_commit_boundary(agent):
    original = agent.loop._run_agent_loop.__func__
    def committed():
        return len(agent.action.records) == 1
    def audit(iteration, tools_used):
        agent.provider._append('action-commit-boundary.jsonl', {
            'event_id': agent.action.event_id,
            'iteration': iteration,
            'tools_used': list(tools_used),
            'committed_records': 1,
            'physical_execution_pending': True,
            'native_loop_sha256': UPSTREAM_SHA256,
            'stop_reason': 'valid_action_committed_wait_for_physical_feedback',
            'synthetic_model_output': False,
        })
    patched = patch_loop(original, committed, audit)
    agent.loop._run_agent_loop = types.MethodType(patched, agent.loop)
    agent._write('action-boundary-adapter.json', {
        'version': 'v6r1',
        'both_rmb_arms_identical': True,
        'native_loop_sha256': UPSTREAM_SHA256,
        'session_persistence': 'unchanged native _process_message and _save_turn',
        'no_argument_repair': True,
        'no_finish_veto': True,
    })

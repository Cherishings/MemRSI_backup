"""Public execution API only: no task state, priorities, or scorer answers."""
import json

CATALOG = {
    **{'serve_' + t: {
        'scope': 'preserved table ' + t,
        'procedure': 'place the white mug on the plate and the pudding to the right of the plate',
        'pause': 'only when the current user request explicitly asks to pause after one placement',
    } for t in 'ABCDE'},
    **{'serve_' + t: {
        'scope': 'preserved table ' + t,
        'procedure': 'place the two task-specified mugs on their respective plates',
    } for t in 'FG'},
    'execute_order': {
        'scope': 'the currently issued kitchen work order',
        'procedure': 'execute that work order using its configured native manipulation skill',
        'binding': 'the public Current kitchen work order instruction supplies the object and destination; '
                   'no object-specific action name or A-G table mapping is required',
    },
    'finish': {'scope': 'whole run', 'procedure': 'declare the shift finished; does not execute a manipulation'},
}

CONTRACT = ('Use report_action once to select one skill, then await actual execution feedback. '
    'All physical actions are serial. Scene routing is automatic, not autonomous navigation. '
    'The following catalog defines executable tool capabilities, not the current task or its answer. '
    'Seeing an object does not create a user request to move it. A skill name is an argument value, '
    'not a file to find or a separate tool. Do not access other trials or write scripts.\n' +
    json.dumps(CATALOG, ensure_ascii=False, sort_keys=True))

def action_parameters():
    return {'type': 'object', 'properties': {
        'skill': {'type': 'string', 'enum': list(CATALOG),
                  'description': 'Choose an argument from the authoritative catalog: ' +
                    json.dumps(CATALOG, ensure_ascii=False, sort_keys=True)},
        'reason': {'type': 'string'}},
        'required': ['skill', 'reason'], 'additionalProperties': False}

"""Narrow learned edits to reasoning and memory procedures, not protocol declarations."""
import re
SCOPE=('Edit only evidence interpretation, authorization/continuation/receipt reasoning, and memory retention or reconciliation. '
       'The runtime contract is reference context, not text to repeat or revise in learned procedures. '
       'Do not put literal runtime field/tool names, output-schema declarations, or numeric output length limits in replacements. '
       'Use training successes and failures to propose general process improvements; preserve all runtime requirements. '
       'This restriction narrows the search space and does not relax any critic criterion.')
def validate(patch):
    for target in ('guidance','update'):
        text=patch[target+'_replacement']
        if re.search(r'\b(?:basis_ids|report_advice|tool_calls|max_tokens|additionalProperties)\b',text,re.I):
            raise ValueError('process_edit_contains_protocol_identifier')
        if re.search(r'\b\d+\s*(?:words?|characters?|tokens?|fields?)\b',text,re.I):
            raise ValueError('process_edit_contains_numeric_protocol_limit')
        if re.search(r'\b(?:JSON\s+schema|tool\s+schema|required\s+fields?|runtime\s+fields?|output\s+schema)\b',text,re.I):
            raise ValueError('process_edit_contains_schema_declaration')

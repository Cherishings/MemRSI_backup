"""Fixed, auditable resource units; not a claim about the gateway's tokenizer."""
import json
from functools import lru_cache

@lru_cache(maxsize=1)
def encoding():
    import tiktoken
    return tiktoken.get_encoding('o200k_base')

def tokens(text):
    return len(encoding().encode(text, disallowed_special=()))

def request_tokens(messages, tools=None):
    # Includes tool schemas and message metadata; same serialization for all arms.
    return tokens(json.dumps({'messages': messages, 'tools': tools or []},
                             ensure_ascii=False, separators=(',', ':')))

def memory_tokens(memory, history):
    return tokens(memory) + tokens(history)

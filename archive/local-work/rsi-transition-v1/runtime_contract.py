"""Read only named frozen interface functions; no evaluation traces or execution."""
import ast,hashlib
from pathlib import Path
NAMES=('public_payload','advice_tools','validate_advice')
def extract(path):
    path=Path(path);text=path.read_text();tree=ast.parse(text)
    functions={n.name:ast.get_source_segment(text,n) for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in NAMES}
    if set(functions)!=set(NAMES):raise ValueError('runtime_contract_function_missing')
    return {'source_path':str(path),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'scope':'existing frozen runtime implementation; not candidate instructions','functions':functions}

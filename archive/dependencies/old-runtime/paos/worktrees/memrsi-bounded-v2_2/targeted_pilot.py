"""Reuse completed exploratory evidence, never relabel it as a new experiment."""
import hashlib
import json
import shutil
from pathlib import Path
from durable_queue import read
from physical_runner import same_process
from replay import dump


def bootstrap_pilot(pointer, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    record = read(Path(pointer))
    if not record or same_process(record['coordinator']):
        raise RuntimeError('pilot_missing_or_still_running')
    source = Path(record['result'])
    report = read(source / 'report.json', {})
    if report.get('status') != 'learning_finished_no_qualified_policy':
        raise RuntimeError('unexpected_pilot_terminal_state')
    if read(source / 'learning/report.json', {}).get('promotions') != 0:
        raise RuntimeError('pilot_parent_changed')
    # Public scenario, capacity and base methods must be identical.
    for name in ('budget.json', 'selected-orders.json'):
        if (source / name).read_bytes() != (out.parent / name).read_bytes():
            raise RuntimeError('pilot_inputs_changed')
    marker = out / 'pilot-reuse.json'
    if marker.exists():
        if read(marker)['source'] != str(source):
            raise RuntimeError('pilot_source_changed')
        return
    source_root = source / 'learning/cycle-0'
    dest_root = out / 'cycle-0'
    dest_root.mkdir(exist_ok=True)
    # No selection, physical trial rows, cycle1 results or test results copied.
    names = ['diagnoses', 'guidance/proposal', 'guidance/critic', 'guidance/probes',
             'update/proposal', 'update/critic', 'update/probes']
    hashes = {}
    for name in names:
        src = source_root / name
        if not src.is_dir():
            raise RuntimeError('pilot_cache_incomplete')
        dst = dest_root / name
        for f in src.rglob('*'):
            if not f.is_file():
                continue
            rel = f.relative_to(source_root)
            target = dest_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(f.read_bytes()).hexdigest()
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                    raise RuntimeError('pilot_cache_changed')
            else:
                shutil.copy2(f, target)
            hashes[str(rel)] = digest
    ledger = read(source / 'learning/learning-call-ledger.json')
    if not ledger or not isinstance(ledger.get('calls'), int):
        raise RuntimeError('pilot_budget_missing')
    dest_ledger = out / 'learning-call-ledger.json'
    if dest_ledger.exists() and read(dest_ledger) != ledger:
        raise RuntimeError('pilot_budget_ambiguous')
    dump(dest_ledger, ledger)
    dump(marker, {'source': str(source), 'reused_cycle': 0,
                  'source_hashes': hashes, 'inherited_ledger': ledger,
                  'selection_revision_after_pilot_observation': True,
                  'not_independent_replication': True,
                  'cycle1_and_validation_not_reused': True})

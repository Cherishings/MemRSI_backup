"""Copy the verified installed SDK closure into a fresh isolated overlay.

Run using /home/xi/envs/agent/bin/python (Python 3.11). Only distribution-owned
site-packages files are read; user settings, credentials and entrypoint scripts
outside site-packages are excluded. Existing environments are never modified.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import platform
import shutil
from pathlib import Path

from packaging.markers import default_environment
from packaging.requirements import Requirement


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target', type=Path, required=True)
    args = parser.parse_args()
    if args.target.exists():
        raise RuntimeError('overlay_target_must_be_new')
    if metadata.version('openai') != '2.54.0' or platform.python_version_tuple()[:2] != ('3', '11'):
        raise RuntimeError('source_runtime_mismatch')
    closure, pending = {}, ['openai']
    while pending:
        name = pending.pop()
        key = name.lower().replace('_', '-')
        if key in closure:
            continue
        if key in {'torch', 'numpy', 'transformers'}:
            raise RuntimeError('execution_stack_must_not_enter_overlay')
        dist = metadata.distribution(name)
        closure[key] = dist
        for text in dist.requires or []:
            requirement = Requirement(text)
            if requirement.marker and not requirement.marker.evaluate({**default_environment(), 'extra': ''}):
                continue
            if requirement.specifier and metadata.version(requirement.name) not in requirement.specifier:
                raise RuntimeError('installed_dependency_does_not_satisfy_constraint')
            pending.append(requirement.name)
    stage = args.target.with_name(args.target.name + '.building')
    stage.mkdir(parents=True, exist_ok=False)
    manifest = {'openai': '2.54.0', 'python': platform.python_version(),
                'source': 'installed agent environment distribution RECORD files only',
                'packages': {}, 'files': {}, 'credentials_copied': False}
    for name, dist in sorted(closure.items()):
        source_root = Path(dist.locate_file('')).resolve()
        if 'site-packages' not in source_root.parts:
            raise RuntimeError('unexpected_distribution_root')
        manifest['packages'][name] = dist.version
        for relative in dist.files or []:
            rel = Path(str(relative))
            if rel.is_absolute() or '..' in rel.parts or '__pycache__' in rel.parts or rel.name == 'direct_url.json':
                continue
            source = Path(dist.locate_file(relative))
            if not source.is_file() or not source.resolve().is_relative_to(source_root):
                continue
            destination = stage / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError('overlay_file_collision')
            shutil.copy2(source, destination)
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise RuntimeError('overlay_copy_hash_mismatch')
            manifest['files'][str(rel)] = digest
    (stage / 'overlay-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    stage.rename(args.target)
    print(json.dumps({'status': 'installed_isolated_overlay', 'packages': manifest['packages'],
                      'files_verified': len(manifest['files'])}))


if __name__ == '__main__':
    main()

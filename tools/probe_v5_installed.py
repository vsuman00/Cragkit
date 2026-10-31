"""Check isolated installed V5 entry points without permitting import-time I/O."""
import argparse
import importlib
import importlib.metadata
import importlib.util
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--profile', choices=['core', 'postgres', 'qdrant', 'qdrant-authoritative', 'tokenizers', 'mcp'], required=True)
args = parser.parse_args()
expected = {'psycopg': args.profile in ('postgres', 'qdrant-authoritative'), 'httpx': args.profile in ('qdrant', 'qdrant-authoritative'),
            'httpx2': args.profile == 'mcp',
            'tiktoken': args.profile in ('tokenizers', 'mcp'), 'mcp': args.profile == 'mcp'}
for name, present in expected.items():
    assert (importlib.util.find_spec(name) is not None) == present, name
for name in ('torch', 'transformers', 'qdrant_client', 'langchain_core'):
    assert importlib.util.find_spec(name) is None, name

def audit(event, _args):
    if event.startswith(('socket.', 'subprocess.')) or event in ('os.system', 'os.posix_spawn'):
        raise RuntimeError('Import attempted external I/O')
sys.addaudithook(audit)
modules = {}
for name in ('cragkit', 'cragkit.qdrant', 'cragkit.qdrant_source', 'cragkit.qdrant_publication',
             'cragkit.qdrant_corrective', 'cragkit.postgres') + (('cragkit_mcp',) if args.profile == 'mcp' else ()):
    module = importlib.import_module(name)
    path = Path(module.__file__).resolve()
    assert path.is_relative_to(Path(sys.prefix).resolve()), name
    modules[name] = str(path)
assert callable(importlib.import_module('cragkit.qdrant_corrective').QdrantCorrectiveBackend)
assert importlib.metadata.version('cragkit') == '0.0.0'
print(json.dumps({'state': 'passed', 'profile': args.profile, 'modules': modules,
    'installed': sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions())}))

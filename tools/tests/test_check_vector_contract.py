"""Keep cross-runtime comparison strict and failures redacted."""
import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    'check_vector_contract', Path(__file__).resolve().parents[1] / 'check_vector_contract.py',
)
assert SPEC and SPEC.loader
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


def test_sql_normalization_preserves_scope_and_placeholder_identity():
    python = 'SELECT count(*) FROM x WHERE tenant=%s AND collection=%s'
    node = 'SELECT count(*)::int FROM x WHERE tenant=$1 AND collection=$2'
    assert CHECK.normalize_sql(python) == CHECK.normalize_sql(node)
    assert CHECK.normalize_sql('SELECT * FROM x WHERE tenant=%s') != CHECK.normalize_sql(
        'SELECT * FROM x',
    )
    assert CHECK.normalize_sql('SELECT * FROM x WHERE tenant=$1 AND collection=$2') != (
        CHECK.normalize_sql('SELECT * FROM x WHERE tenant=$2 AND collection=$1')
    )


def test_contract_failure_does_not_log_subprocess_or_provider_details(monkeypatch, capsys):
    async def failure():
        raise RuntimeError('private provider SQL password')

    monkeypatch.setattr(CHECK, 'check', failure)
    assert CHECK.main() == 1
    output = capsys.readouterr().out
    assert 'vector_contract_failed' in output
    assert 'private' not in output and 'password' not in output


def test_sql_normalization_preserves_quoted_values_and_identifiers():
    assert CHECK.normalize_sql("SELECT 'UTF8'") != CHECK.normalize_sql("SELECT 'utf8'")
    assert CHECK.normalize_sql("SELECT 'a  b'") != CHECK.normalize_sql("SELECT 'a b'")
    assert CHECK.normalize_sql('SELECT "Field"') != CHECK.normalize_sql('SELECT "field"')
    assert CHECK.normalize_sql("SELECT '%s', value=%s") == "select '%s' , value=$1"

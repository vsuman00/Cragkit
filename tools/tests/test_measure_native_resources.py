"""Reject incomplete native evidence instead of interpreting it as a fast run."""
from copy import deepcopy
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import measure_native_resources as N


def observation():
    stage = dict(concurrency=1, elapsed_ms=50, latency_ms=[1]*20, context_tokens=[20]*20,
                 attempts=[1]*20, provider_calls=[1]*20, throughput_per_second=400)
    second = deepcopy(stage)
    second['concurrency'] = 2
    return dict(revision='RST-r1', runtime='python', version='1.0.0rc1', ingestion_ms=[1,2,3],
        retrieval=[stage,second], checks={name:True for name in N.REQUIRED_CHECKS},
        peak_rss_bytes=100, provider_http_calls=0, active_dispatch_observation=1, database_logical_bytes=1024)


@pytest.mark.parametrize('mutation', ['nan','missing','check','http','deadline','tokens','bool','stages','ingest','rss','check_missing','version'])
def test_invalid_observation_cannot_pass_resource_gate(mutation):
    value = observation()
    if mutation == 'nan': value['retrieval'][0]['latency_ms'][0] = float('nan')
    if mutation == 'missing': value['retrieval'][0]['latency_ms'].pop()
    if mutation == 'check': value['checks']['cleanup_verified'] = False
    if mutation == 'http': value['provider_http_calls'] = 1
    if mutation == 'deadline': value['retrieval'][0]['latency_ms'] = [25001]*20
    if mutation == 'tokens': value['retrieval'][0]['context_tokens'][0] = 20001
    if mutation == 'bool': value['retrieval'][0]['provider_calls'][0] = True
    if mutation == 'stages': value['retrieval'][1]['concurrency'] = 1
    if mutation == 'ingest': value['ingestion_ms'].pop()
    if mutation == 'rss': value['peak_rss_bytes'] = 0
    if mutation == 'check_missing': value['checks'].pop('active_cancelled')
    if mutation == 'version': value['version'] = 'wrong'
    with pytest.raises((N.NativeResourceError, ValueError)):
        N.validate_observation(value, 'python', {'retrieval_p95_deadline_ms':25000})


def test_parent_uses_raw_latencies_to_compute_p95():
    value = observation()
    actual = N.validate_observation(value, 'python', {'retrieval_p95_deadline_ms':25000})
    assert actual['retrieval'][0]['latency_summary_ms']['p95'] == 1
    assert actual['retrieval'][0]['observed_requests_per_second'] == 400


def test_oversized_child_output_is_reaped_without_returning_its_content():
    import asyncio
    script = "import sys,time; sys.stdout.write('private-marker'*16000);sys.stdout.flush();time.sleep(10)"
    with pytest.raises(RuntimeError) as error:
        asyncio.run(N.child([sys.executable, '-I', '-c', script], timeout=2))
    assert 'private-marker' not in str(error.value)


def test_child_watchdog_does_not_wait_for_unbounded_native_work():
    import asyncio
    with pytest.raises(TimeoutError):
        asyncio.run(N.child([sys.executable, '-I', '-c', 'import time;time.sleep(10)'], timeout=.05))

"""Offline gated-sender faults; no account access, live TLS or quality evidence."""
import asyncio
import json
from pathlib import Path
import sys
import time

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluation_payloads import EvaluationPayloadGate
from live_evaluation_budget import LiveBudgetError
from provider_adapters import COHERE_MODEL, ProviderAdapterError, ProviderRequest
from provider_journal import load_recordings
from recorded_provider import RecordedProviderSend

SOURCE, QUERY = 'Approved synthetic source.', 'Approved question?'


def request(text=SOURCE):
    return ProviderRequest('cohere', COHERE_MODEL, json.dumps(dict(model=COHERE_MODEL,
        query=QUERY, documents=[text], top_n=1, max_tokens_per_doc=4096)).encode(), 'a'*64)


def response(tokens=2):
    return dict(results=[dict(index=0, relevance_score=.9)], meta=dict(billed_units=dict(input_tokens=tokens)))


def reply(tokens=2):
    return httpx.Response(200, headers={'content-type':'application/json'},
        stream=httpx.ByteStream(json.dumps(response(tokens)).encode()))


def sender(tmp_path, handler=None):
    return RecordedProviderSend({'cohere':'fake-key'}, EvaluationPayloadGate([SOURCE],[QUERY]),
        tmp_path/'recordings', enabled=True, transport=httpx.MockTransport(handler or (
            lambda request:reply())))


async def invoke(send, row=None):
    return await send(row or request(), deadline=time.monotonic()+10, max_response_bytes=65536)


def test_gate_budget_durable_pending_http_complete_seal_and_mock_replay(tmp_path):
    calls = []
    def handler(row):
        calls.append(True)
        pending=tmp_path/'recordings/001.pending.json'
        assert pending.exists() and SOURCE not in pending.read_text() and 'fake-key' not in pending.read_text()
        return reply()
    send=sender(tmp_path,handler)
    async def run():
        async with send:
            raw=await invoke(send)
            assert send.snapshot()['budget']['records'][0]['reported_input_tokens']==2
        assert send.snapshot()['cleanup_verified'] and not send.snapshot()['failed']
        return raw
    raw=asyncio.run(run())
    assert calls==[True] and send.snapshot()['journal']['sealed']
    with pytest.raises(ProviderAdapterError):load_recordings(tmp_path/'recordings')
    tape=load_recordings(tmp_path/'recordings',require_live=False)
    assert len(tape)==1 and tape[0].response==raw
    assert SOURCE not in str(send.snapshot()) and 'fake-key' not in repr(send)


def test_explicit_enable_exact_gate_and_issued_counter_before_open(tmp_path):
    gate=EvaluationPayloadGate([SOURCE],[QUERY])
    for options in ({},{'enabled':1},{'enabled':True,'counter':object()}):
        with pytest.raises(ProviderAdapterError):
            RecordedProviderSend({'cohere':'fake-key'},gate,tmp_path/'absent',**options)
    with pytest.raises(ProviderAdapterError):RecordedProviderSend({'cohere':'fake'},object(),tmp_path/'absent',enabled=True)
    assert not (tmp_path/'absent').exists()


def test_unapproved_payload_has_no_attempt_or_http_and_freezes(tmp_path):
    calls=[]
    send=sender(tmp_path,lambda row:calls.append(row))
    async def run():
        async with send:
            with pytest.raises(Exception):await invoke(send,request('private unapproved source'))
            with pytest.raises(ProviderAdapterError):await invoke(send)
        assert send.snapshot()['budget']['attempts']==0 and send.snapshot()['failed']
    asyncio.run(run())
    assert not calls and not (tmp_path/'recordings/seal.json').exists()


def test_predispatch_journal_fault_no_http_retains_bound(tmp_path,monkeypatch):
    import provider_journal
    original=provider_journal._write
    def write(fd,name,value):
        if name.endswith('.pending.json'):raise OSError('private directory')
        return original(fd,name,value)
    monkeypatch.setattr(provider_journal,'_write',write)
    calls=[];send=sender(tmp_path,lambda row:calls.append(row))
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError,match='provider_journal_failed') as error:await invoke(send)
            assert error.value.__context__ is None
        assert send.snapshot()['budget']['records'][0]['estimated_input_tokens']==32768
        assert send.snapshot()['budget']['pending']==0
    asyncio.run(run())
    assert not calls and not (tmp_path/'recordings/seal.json').exists()


def test_post_http_journal_write_failure_preserves_reported_tokens_and_original_error(tmp_path,monkeypatch):
    import provider_journal
    original=provider_journal._write
    def write(fd,name,value):
        if name.endswith('.complete.json'):raise OSError('private write failure')
        return original(fd,name,value)
    monkeypatch.setattr(provider_journal,'_write',write)
    send=sender(tmp_path)
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError,match='provider_journal_failed') as error:await invoke(send)
            assert error.value.__context__ is None
        snap=send.snapshot()
        assert snap['budget']['records'][0]['reported_input_tokens']==2
        assert snap['budget']['estimated_cost_usd']=='0.00000004'
        assert snap['budget']['pending']==0 and snap['failed']
    asyncio.run(run())
    with pytest.raises(ProviderAdapterError):load_recordings(tmp_path/'recordings',require_live=False)


def test_usage_overrun_keeps_larger_recorded_charge_and_unsealed_journal(tmp_path):
    send=sender(tmp_path,lambda row:reply(40000))
    async def run():
        async with send:
            with pytest.raises(LiveBudgetError,match='live_budget_overrun'):await invoke(send)
        snap=send.snapshot()
        assert snap['budget']['closed'] and snap['budget']['records'][0]['estimated_input_tokens']==40000
        assert snap['budget']['pending']==0 and snap['journal']['failed'] and not snap['journal']['sealed']
    asyncio.run(run())


def test_transport_failure_unknown_usage_no_retry(tmp_path):
    calls=[]
    def handler(row):calls.append(True);raise httpx.ConnectError('private fake-key',request=row)
    send=sender(tmp_path,handler)
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError,match='provider_http_failed') as error:await invoke(send)
            assert error.value.__context__ is None
            with pytest.raises(ProviderAdapterError):await invoke(send)
        assert send.snapshot()['budget']['records'][0]['reported_input_tokens'] is None
        assert send.snapshot()['budget']['records'][0]['estimated_input_tokens']==32768
    asyncio.run(run())
    assert calls==[True]


def test_cancellation_records_uncertain_and_closes_all(tmp_path):
    async def run():
        entered=asyncio.Event()
        async def handler(row):entered.set();await asyncio.Event().wait()
        send=sender(tmp_path,handler)
        async with send:
            task=asyncio.create_task(invoke(send))
            await entered.wait();task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        assert send.snapshot()['failed'] and send.snapshot()['cleanup_verified']
        assert send.snapshot()['budget']['pending']==0 and not send.snapshot()['journal']['sealed']
        assert send._http._client.is_closed
    asyncio.run(run())


def test_http_close_fault_leaves_unsealed_and_journal_close_is_attempted(tmp_path):
    send=sender(tmp_path)
    original=send._http.aclose
    async def close():await original();raise OSError('private close')
    send._http.aclose=close
    async def run():
        with pytest.raises(ProviderAdapterError,match='provider_recorded_failed') as error:
            async with send:await invoke(send)
        assert error.value.__context__ is None
        assert send._journal._fd is None
        assert send.snapshot()['failed'] and not send.snapshot()['cleanup_verified']
        assert not send.snapshot()['journal']['sealed']
    asyncio.run(run())


def test_actual_http_client_close_keeps_its_fixed_error_and_blocks_sealing(tmp_path):
    class CloseFailure(httpx.MockTransport):
        async def aclose(self):
            raise httpx.ConnectError('fake-key private request close')
    send = RecordedProviderSend({'cohere': 'fake-key'},
        EvaluationPayloadGate([SOURCE], [QUERY]), tmp_path / 'recordings', enabled=True,
        transport=CloseFailure(lambda row: reply()))
    async def run():
        with pytest.raises(ProviderAdapterError, match='^provider_http_close_failed$') as error:
            async with send:
                await invoke(send)
        assert error.value.__cause__ is None and error.value.__context__ is None
        assert send._journal._fd is None
        snapshot = send.snapshot()
        assert snapshot['failed'] and not snapshot['cleanup_verified']
        assert not snapshot['journal']['sealed']
    asyncio.run(run())


def test_last_journal_fd_close_fault_preserves_durable_seal_but_fails_exit(tmp_path,monkeypatch):
    import provider_journal
    send=sender(tmp_path)
    original=provider_journal.EvaluationJournal.__exit__
    def close(self,*args):original(self,*args);raise OSError('private fd close')
    monkeypatch.setattr(provider_journal.EvaluationJournal,'__exit__',close)
    async def run():
        with pytest.raises(ProviderAdapterError,match='provider_recorded_failed') as error:
            async with send:await invoke(send)
        assert error.value.__context__ is None
        snap=send.snapshot()
        assert snap['failed'] and not snap['cleanup_verified'] and snap['journal']['sealed']
    asyncio.run(run())
    assert len(load_recordings(tmp_path/'recordings',require_live=False))==1


def test_repeated_explicit_requests_keep_distinct_ordered_attempts(tmp_path):
    send=sender(tmp_path)
    async def run():
        async with send:
            await invoke(send);await invoke(send)
        assert send.snapshot()['budget']['attempts']==2
    asyncio.run(run())
    rows=load_recordings(tmp_path/'recordings',require_live=False)
    assert len(rows)==2 and rows[0].replay_key==rows[1].replay_key


def test_openai_uses_issued_exact_counter_and_retains_reported_usage(tmp_path):
    from cragkit.context import Cl100kCounter
    from provider_adapters import OPENAI_MODEL
    asset=Path(__file__).resolve().parents[2]/'artifacts/tokenizers/cl100k_base.tiktoken'
    if not asset.exists():pytest.skip('explicit pinned tokenizer asset required')
    counter=Cl100kCounter.from_file(asset)
    count=counter.count(QUERY)
    raw=json.dumps(dict(model=OPENAI_MODEL,data=[dict(index=0,embedding=[1.]+[0.]*1535)],
        usage=dict(prompt_tokens=count,total_tokens=count))).encode()
    row=ProviderRequest('openai',OPENAI_MODEL,json.dumps(dict(model=OPENAI_MODEL,dimensions=1536,encoding_format='float',input=[QUERY])).encode(),'b'*64)
    transport=httpx.MockTransport(lambda request:httpx.Response(200,headers={'content-type':'application/json'},stream=httpx.ByteStream(raw)))
    send=RecordedProviderSend({'openai':'fake-key'},EvaluationPayloadGate([SOURCE],[QUERY]),
        tmp_path/'recordings',counter=counter,enabled=True,transport=transport)
    async def run():
        async with send:assert await invoke(send,row)==raw
        record=send.snapshot()['budget']['records'][0]
        assert record['input_token_ceiling']==record['reported_input_tokens']==count
    asyncio.run(run())


def test_response_validation_failure_unknown_bound_and_unreplayable(tmp_path):
    send=sender(tmp_path,lambda row:httpx.Response(200,headers={'content-type':'application/json'},stream=httpx.ByteStream(b'{"results":[]}')))
    async def run():
        async with send:
            with pytest.raises(Exception):await invoke(send)
        snap=send.snapshot()
        assert snap['failed'] and not snap['journal']['sealed']
        assert snap['budget']['records'][0]['estimated_input_tokens']==32768
    asyncio.run(run())
    with pytest.raises(ProviderAdapterError):load_recordings(tmp_path/'recordings',require_live=False)


def test_post_http_disk_failure_still_records_overrun_without_masking_journal_error(tmp_path,monkeypatch):
    import provider_journal
    original=provider_journal._write
    def write(fd,name,value):
        if name.endswith('.complete.json'):raise OSError('private failure')
        return original(fd,name,value)
    monkeypatch.setattr(provider_journal,'_write',write)
    send=sender(tmp_path,lambda row:reply(40000))
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError,match='provider_journal_failed'):await invoke(send)
        snap=send.snapshot()
        assert snap['budget']['closed'] and snap['budget']['records'][0]['reported_input_tokens']==40000
        assert snap['budget']['records'][0]['estimated_input_tokens']==40000 and snap['budget']['pending']==0
    asyncio.run(run())


def test_existing_run_directory_cannot_automatically_resend(tmp_path):
    first=sender(tmp_path)
    async def run():
        async with first:await invoke(first)
        calls=[]
        second=sender(tmp_path,lambda row:calls.append(True))
        with pytest.raises(ProviderAdapterError):
            async with second:pytest.fail('existing directory was reused')
        assert not calls and second.snapshot()['failed']
    asyncio.run(run())
    assert len(load_recordings(tmp_path/'recordings',require_live=False))==1


def test_concurrent_call_cannot_charge_or_dispatch_second_attempt(tmp_path):
    async def run():
        entered,release=asyncio.Event(),asyncio.Event()
        async def handler(row):entered.set();await release.wait();return reply()
        send=sender(tmp_path,handler)
        async with send:
            task=asyncio.create_task(invoke(send))
            await entered.wait()
            with pytest.raises(ProviderAdapterError,match='concurrent_dispatch'):await invoke(send)
            release.set();await task
        assert send.snapshot()['budget']['attempts']==1
    asyncio.run(run())


def test_repeated_cancellation_during_close_still_closes_journal_and_http(tmp_path):
    async def run():
        send=sender(tmp_path)
        entered,release=asyncio.Event(),asyncio.Event()
        original=send._http.aclose
        async def close():entered.set();await release.wait();await original()
        send._http.aclose=close
        async def operation():
            async with send:await invoke(send)
        task=asyncio.create_task(operation())
        await entered.wait()
        task.cancel();await asyncio.sleep(0);task.cancel();await asyncio.sleep(0)
        release.set()
        with pytest.raises(asyncio.CancelledError):await task
        assert send._http._client.is_closed and send._journal._fd is None
        assert send.snapshot()['failed'] and not send.snapshot()['journal']['sealed']
    asyncio.run(run())


def test_http_cleanup_has_separate_bounded_allowance_and_always_closes_journal(tmp_path,monkeypatch):
    import recorded_provider
    monkeypatch.setattr(recorded_provider,'_CLOSE_TIMEOUT',.02)
    async def run():
        send=sender(tmp_path)
        original=send._http.aclose
        cancelled=asyncio.Event()
        async def close():
            try:
                await asyncio.Event().wait()
            finally:
                await original()
                cancelled.set()
        send._http.aclose=close
        started=time.monotonic()
        with pytest.raises(ProviderAdapterError,match='provider_recorded_failed') as error:
            async with send:await invoke(send)
        assert time.monotonic()-started < .5
        assert error.value.__context__ is None
        assert send._journal._fd is None
        assert send.snapshot()['failed'] and not send.snapshot()['cleanup_verified']
        assert not send.snapshot()['journal']['sealed']
        await cancelled.wait()
        await asyncio.sleep(0)
    asyncio.run(run())


def test_missing_configured_provider_key_is_pre_admission_even_with_issued_counter(tmp_path):
    from cragkit.context import Cl100kCounter
    from provider_adapters import OPENAI_MODEL
    asset=Path(__file__).resolve().parents[2]/'artifacts/tokenizers/cl100k_base.tiktoken'
    if not asset.exists():pytest.skip('explicit pinned tokenizer asset required')
    counter=Cl100kCounter.from_file(asset)
    calls=[]
    send=RecordedProviderSend({'cohere':'fake-key'},EvaluationPayloadGate([SOURCE],[QUERY]),
        tmp_path/'recordings',counter=counter,enabled=True,transport=httpx.MockTransport(lambda row:calls.append(True)))
    row=ProviderRequest('openai',OPENAI_MODEL,json.dumps(dict(model=OPENAI_MODEL,dimensions=1536,encoding_format='float',input=[QUERY])).encode(),'c'*64)
    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError,match='provider_recorded_invalid'):await invoke(send,row)
        assert send.snapshot()['budget']['attempts']==0
        assert send.snapshot()['journal']['attempts']==0
        assert not list((tmp_path/'recordings').glob('*.pending.json'))
    asyncio.run(run())
    assert not calls


def test_cleanup_returns_before_cancellation_resistant_task_and_observes_late_error(tmp_path,monkeypatch):
    import recorded_provider
    monkeypatch.setattr(recorded_provider,'_CLOSE_TIMEOUT',.02)
    async def run():
        release,finished=asyncio.Event(),asyncio.Event()
        observed=[]
        class TrackingTask(asyncio.Task):
            def exception(self):
                observed.append(True)
                return super().exception()
        def create(coroutine):
            return TrackingTask(coroutine,loop=asyncio.get_running_loop())
        monkeypatch.setattr(recorded_provider.asyncio,'create_task',create)
        send=sender(tmp_path)
        original=send._http.aclose
        async def close():
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await release.wait()
                await original()
                finished.set()
                raise RuntimeError('private late cleanup failure')
        send._http.aclose=close
        started=time.monotonic()
        with pytest.raises(ProviderAdapterError,match='provider_recorded_failed'):
            async with send:await invoke(send)
        assert time.monotonic()-started < .5
        assert send._journal._fd is None and not send.snapshot()['cleanup_verified']
        release.set()
        await finished.wait()
        await asyncio.sleep(0)
        assert observed and send._http._client.is_closed
    asyncio.run(run())


@pytest.mark.parametrize('status,code', [
    (401, 'provider_http_auth_failed'),
    (403, 'provider_http_auth_failed'),
    (429, 'provider_http_rate_limited'),
    (500, 'provider_http_server_failed'),
    (503, 'provider_http_server_failed'),
])
def test_fixed_http_category_survives_private_journal_without_response_body(tmp_path, status, code):
    class UnreadableStream(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            pytest.fail('Error response body was consumed')
            yield b''

        async def aclose(self):
            self.closed = True

    stream, calls = UnreadableStream(), []

    def handler(row):
        calls.append(True)
        return httpx.Response(status, headers={'x-private': 'synthetic-private-value'}, stream=stream)

    send = sender(tmp_path, handler)

    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError, match='^' + code + '$') as error:
                await invoke(send)
            assert error.value.__context__ is None and error.value.__cause__ is None
            with pytest.raises(ProviderAdapterError):
                await invoke(send)

    asyncio.run(run())
    assert calls == [True] and stream.closed
    directory = tmp_path / 'recordings'
    assert json.loads((directory / 'failure.json').read_text()) == {'ordinal': 1, 'code': code}
    assert not (directory / 'seal.json').exists()
    assert not list(directory.glob('*.response'))
    assert all('fake-key' not in p.read_text() and 'synthetic-private-value' not in p.read_text()
               for p in directory.iterdir())
    snapshot = send.snapshot()
    assert snapshot['cleanup_verified'] and snapshot['failed']
    assert snapshot['budget']['attempts'] == 1 and snapshot['budget']['pending'] == 0
    assert snapshot['budget']['records'][0]['reported_input_tokens'] is None
    assert snapshot['budget']['records'][0]['estimated_input_tokens'] == 32768
    with pytest.raises(ProviderAdapterError):
        load_recordings(directory, require_live=False)


@pytest.mark.parametrize('code', ['provider_pacing_invalid', 'provider_pacing_failed'])
def test_fixed_predispatch_pacing_failure_is_recorded_without_http(tmp_path, code):
    calls = []
    send = sender(tmp_path, lambda row: calls.append(True))

    class RefusingPacer:
        async def wait(self, *args, **kwargs):
            raise ProviderAdapterError(code)

    send._http._pacer = RefusingPacer()

    async def run():
        async with send:
            with pytest.raises(ProviderAdapterError, match='^' + code + '$'):
                await invoke(send)

    asyncio.run(run())
    assert not calls
    assert json.loads((tmp_path / 'recordings/failure.json').read_text()) == {'ordinal': 1, 'code': code}
    assert not (tmp_path / 'recordings/seal.json').exists()

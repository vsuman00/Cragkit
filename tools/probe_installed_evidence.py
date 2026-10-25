"""Exercise installed native evidence contracts with explicit public fixtures."""
import argparse
import asyncio
import hashlib
import importlib
import json
from pathlib import Path
import sys

def deny_external_io(event, args):
    if event.startswith('socket.'):
        if event == 'socket.__new__' and len(args) > 1 and args[1] == 1:
            return  # asyncio's local AF_UNIX wakeup socket pair
        raise RuntimeError('external_io_denied')
    if event.startswith('subprocess.') or event in ('os.system', 'os.exec', 'os.posix_spawn', 'os.fork'):
        raise RuntimeError('external_process_denied')


sys.addaudithook(deny_external_io)
import time


def require(value):
    if not value:
        raise ValueError('installed_contract_failed')


async def probe(args):
    import cragkit
    prefix = Path(args.prefix).resolve()
    require(Path(sys.prefix).resolve() == prefix)
    require(Path(cragkit.__file__).resolve().is_relative_to(prefix))
    names = ('context', 'packing', 'assessment', 'evidence', '_postgres_session', '_postgres_filters', 'contracts', 'errors')
    modules = {name: importlib.import_module('cragkit.' + name) for name in names}
    require(all(Path(module.__file__).resolve().is_relative_to(prefix) for module in modules.values()))
    context, packing, assessment, pipeline = (modules[name] for name in ('context', 'packing', 'assessment', 'evidence'))
    errors = modules['errors']
    fixtures = Path(args.fixtures)
    load = lambda name: json.loads((fixtures / name).read_text(encoding='utf-8'))
    sources, contexts, packs, assessments, pipelines = (load(name) for name in
        ('retrieval.json', 'context.json', 'packing.json', 'assessment.json', 'evidence-pipeline.json'))
    require((len(sources['source_cases']), len(contexts['cases']), len(contexts['token_cases']), len(packs['cases']),
             len(assessments['cases']), len(pipelines['cases'])) == (23, 8, 127, 17, 35, 6))

    class Cursor:
        def __init__(self, rows): self.rows = rows
        async def fetchall(self): return self.rows

    class Connection:
        def __init__(self, rows): self.rows = [tuple(row) for row in rows]; self.calls = []
        async def execute(self, sql, params=None):
            self.calls.append((sql, params))
            return Cursor([] if 'statement_timeout' in sql else self.rows)

    source_results = []
    for case in sources['source_cases']:
        request = modules['contracts'].parse_request(case['request'])
        scope = modules['contracts'].parse_scope(case['scope'])
        candidate = modules['_postgres_session'].LexicalCandidate.model_validate(case['candidate'])
        connection = Connection(case['rows'])
        predicate, parameters = modules['_postgres_filters'].compile_filters(request.required_filters)
        handle = modules['_postgres_session'].ScopedSession(connection, request, scope, time.monotonic() + 5, predicate, parameters)
        try:
            result = (await handle.fetch_evidence(candidate, max_source_bytes=case['max_source_bytes'])).model_dump(mode='json')
            require('error' not in case and result == case['expected'])
            source_results.append(result)
        except errors.CragkitError as error:
            require(error.code == case.get('error'))
            if error.code == 'unauthorized_scope': require(not connection.calls)
            source_results.append({'error': error.code})

    counter = context.Cl100kCounter.from_file(args.tokenizer)
    output = {'revision': 'INST-r1', 'source_cases': source_results, 'context': {'cases': [], 'token_counts': []},
              'packing': [], 'assessment': [], 'pipeline': []}
    for case in contexts['cases']:
        try:
            result = context.count_context(case['evidence'], max_tokens=case['max_tokens'], reserve=case['reserve'],
                counting_mode=case['counting_mode'], counter=counter if case['counting_mode'] == 'strict' else None)
            require('expected_error' not in case)
            require(result['context'] == case['expected_context'] and result['context_tokens'] == case['expected_context_tokens'])
            require(result['total_tokens'] <= case['max_tokens'])
            output['context']['cases'].append(result)
        except errors.CragkitError as error:
            require(error.code == case.get('expected_error')); output['context']['cases'].append({'error': error.code})
    for case in contexts['token_cases']:
        tokens = counter.count(case['text']); require(tokens == case['expected_tokens'])
        output['context']['token_counts'].append({'id': case['id'], 'tokens': tokens})
    for case in packs['cases']:
        options = dict(case['options'])
        if options.get('counting_mode') == 'strict': options['counter'] = counter
        try:
            result = await packing.pack_evidence(case['evidence'], case['sources'], deadline=time.monotonic()+5, **options)
            require('expected_error' not in case and [item['text'] for item in result['evidence']] == case['expected_texts'])
            require(result['total_tokens'] <= options['max_tokens'] and json.loads(result['context']) == result['evidence'])
            for item in result['evidence']:
                source = next(value for value in case['sources'] if all(value[key] == item[key] for key in ('collection','document_id','revision_id')))
                raw = source['text'].encode()
                require(raw[item['start_byte']:item['end_byte']].decode() == item['text'])
                require(hashlib.sha256(raw).hexdigest() == item['source_sha256'])
                require(hashlib.sha256(item['text'].encode()).hexdigest() == item['text_sha256'])
            require(result['omitted_count'] == len(case['evidence']) - sum(len(ids) for ids in result['aliases'].values()))
            counted = context.count_context(result['evidence'], **{key: value for key, value in options.items() if key in ('max_tokens','reserve','counting_mode','counter')})
            require(all(result[key] == value for key, value in counted.items()))
            output['packing'].append(result)
        except errors.CragkitError as error:
            require(error.code == case.get('expected_error')); output['packing'].append({'error': error.code})
    for case in assessments['cases']:
        try:
            result = assessment.assess_evidence(case['query'], case['evidence'], case['policy'])
            require('expected_error' not in case and result['status'] == case['expected_status'])
            require([facet['state'] for facet in result['facets']] == case['expected_states'])
            assessment.validate_assessment(case['evidence'], result['facets'])
            output['assessment'].append(result)
        except errors.CragkitError as error:
            require(error.code == case.get('expected_error')); output['assessment'].append({'error': error.code})
    for case in pipelines['cases']:
        options = dict(case['options'])
        if options.get('counting_mode') == 'strict': options['counter'] = counter
        try:
            result = await pipeline.pack_and_assess(case['query'], case['evidence'], case['sources'],
                policy=case['policy'], deadline=time.monotonic()+5, **options)
            require('expected_error' not in case and result['status'] == case['expected_status'])
            require([facet['state'] for facet in result['facets']] == case['expected_states'])
            require(result['rebalance_count'] == case['expected_rebalance_count'] and result['rebalance_count'] <= 1)
            require(result['total_tokens'] <= options['max_tokens'] and json.loads(result['context']) == result['evidence'])
            assessment.validate_assessment(result['evidence'], result['facets'])
            output['pipeline'].append(result)
        except errors.CragkitError as error:
            require(error.code == case.get('expected_error')); output['pipeline'].append({'error': error.code})
    return output


def main():
    parser = argparse.ArgumentParser()
    for name in ('fixtures', 'tokenizer', 'prefix'): parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    try: result = asyncio.run(probe(args))
    except Exception:
        print(json.dumps({'state': 'failed', 'code': 'installed_evidence_failed'})); return 1
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':'))); return 0


if __name__ == '__main__': raise SystemExit(main())

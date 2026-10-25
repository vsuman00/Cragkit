"""Show partial reviewed coverage and an exact one-token evidence budget."""
import argparse
import asyncio
from hashlib import sha256
import json
from pathlib import Path
import sys


from cragkit.context import Cl100kCounter
from cragkit.evidence import pack_and_assess


def digest(text):
    return sha256(text.encode()).hexdigest()


def anchor(document, text):
    return dict(claim_id='reviewed', collection='public-example', document_id=document, revision_id='r1',
                source_sha256=digest(text), start_byte=0, end_byte=len(text.encode()), text=text)


async def demo(tokenizer):
    query = 'What are the retry limit and delay?'
    retry = anchor('retry', 'Retry at most three times.')
    delay = anchor('delay', 'Wait ten seconds.')
    evidence = dict(evidence_id='retry', collection=retry['collection'], document_id=retry['document_id'],
                    revision_id='r1', chunk_id='retry', source_locator='synthetic:example', start_byte=0,
                    end_byte=retry['end_byte'], text=retry['text'], source_sha256=retry['source_sha256'],
                    text_sha256=digest(retry['text']))
    source = {key: retry[key] for key in ('collection', 'document_id', 'revision_id', 'source_sha256', 'text')}
    policy = dict(policy_id='public-example', version='1', query_sha256=digest(query), facets=[
        dict(facet_id='retry', question='Retry limit?', required=True, absence='missing', anchors=[retry]),
        dict(facet_id='delay', question='Retry delay?', required=True, absence='missing', anchors=[delay]),
    ])
    counter = Cl100kCounter.from_file(tokenizer)
    common = dict(counter=counter, counting_mode='strict', policy=policy, surrounding_bytes=0)
    partial = await pack_and_assess(query, [evidence], [source], deadline=asyncio.get_running_loop().time()+5,
                                   max_tokens=20000, reserve=256, **common)
    strict = await pack_and_assess(query, [evidence], [source], deadline=asyncio.get_running_loop().time()+5,
                                  max_tokens=1, reserve=0, **common)
    assert partial['status'] == 'partial' and [facet['state'] for facet in partial['facets']] == ['supported', 'missing']
    assert strict['status'] == 'insufficient' and strict['context'] == '[]' and strict['context_tokens'] == 1
    return {'partial': partial, 'strict_budget': strict}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tokenizer', required=True)
    parser.add_argument('--prefix')
    args = parser.parse_args()
    if args.prefix:
        import cragkit
        import cragkit.context
        import cragkit.evidence
        prefix = Path(args.prefix).resolve()
        assert Path(sys.prefix).resolve() == prefix
        assert all(Path(module.__file__).resolve().is_relative_to(prefix)
                   for module in (cragkit, cragkit.context, cragkit.evidence))
    print(json.dumps(asyncio.run(demo(args.tokenizer)), ensure_ascii=False, separators=(',', ':')))


if __name__ == '__main__': main()

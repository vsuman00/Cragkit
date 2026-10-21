"""Bounded canonical UTF-8 spans; byte profiles make no model-token guarantee."""
from __future__ import annotations

from hashlib import sha256
from inspect import iscoroutine
import re
from typing import Callable, Iterator, Literal

from pydantic import BaseModel, ConfigDict, Field

from .errors import InvalidRequest


class CanonicalChunk(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    chunk_id: str
    ordinal: int
    start_byte: int
    end_byte: int
    text: str = Field(repr=False)
    text_sha256: str
    oversized_split: bool
    token_count: int | None


class CanonicalDocument(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra='forbid')
    canonical_text: str = Field(repr=False)
    source_sha256: str
    canonical_sha256: str
    parser_id: str
    chunker_profile: str
    format: Literal['text/plain', 'text/markdown']
    tokenizer_id: str | None
    token_count: int | None
    chunks: tuple[CanonicalChunk, ...]


def _integer(value: object, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise InvalidRequest()
    return value


def _blocks(text: str, markdown: bool) -> Iterator[str]:
    current: list[str] = []
    boundary = False
    fence: str | None = None
    for match in re.finditer(r'[^\n]*\n|[^\n]+$', text):
        line = match.group()
        body = line[:-1] if line.endswith('\n') else line
        if fence is not None:
            current.append(line)
            if re.fullmatch(r' {0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}[ \t]*', body):
                fence = None
                boundary = True
            continue
        blank = re.fullmatch(r'[ \t]*', body) is not None
        opening = re.match(r' {0,3}(`{3,}|~{3,})', body) if markdown and not blank else None
        heading = markdown and re.match(r' {0,3}#{1,6}(?:[ \t]|$)', body) is not None
        if not blank and (boundary or opening or heading) and current:
            yield ''.join(current)
            current = []
        if not blank:
            boundary = False
        current.append(line)
        if opening:
            fence = opening.group(1)
        elif heading or blank:
            boundary = True
    if current:
        yield ''.join(current)


def canonicalize(
    source: str | bytes, *, format: str = 'text/plain', max_source_bytes: int = 1_048_576,
    target_bytes: int = 2048, max_chunk_bytes: int = 32_768,
    token_counter: Callable[[str], int] | None = None, tokenizer_id: str | None = None,
    token_target: int | None = None, max_tokens: int | None = None,
) -> CanonicalDocument:
    """Preserve exact canonical slices. Caller counters must be deterministic and bounded.

    Token-mode greedy splitting is conservative, not an optimal partition search.
    Counter code and its external effects remain the caller's responsibility.
    """
    if not isinstance(format, str) or format not in ('text/plain', 'text/markdown'):
        raise InvalidRequest()
    _integer(max_source_bytes, 1, 16_777_216)
    _integer(max_chunk_bytes, 4, 32_768)
    _integer(target_bytes, 1, max_chunk_bytes)
    token_mode = any(value is not None for value in (token_counter, tokenizer_id, token_target, max_tokens))
    token_max = token_goal = 0
    if token_mode:
        if not callable(token_counter) or not isinstance(tokenizer_id, str) or re.fullmatch(r'[A-Za-z0-9_.:-]{1,64}', tokenizer_id) is None:
            raise InvalidRequest()
        token_max = _integer(max_tokens, 1, 1_000_000)
        token_goal = _integer(token_target, 1, token_max)
    raw = b''
    text = ''
    invalid_encoding = False
    try:
        if type(source) is str:
            if len(source) > max_source_bytes:
                raise InvalidRequest()
            raw = source.encode('utf-8', errors='strict')
        elif type(source) is bytes:
            raw = source
        else:
            raise InvalidRequest()
        if len(raw) > max_source_bytes:
            raise InvalidRequest()
        text = raw.decode('utf-8', errors='strict')
    except UnicodeError:
        invalid_encoding = True
    if invalid_encoding:
        raise InvalidRequest() from None
    if text.startswith('\ufeff'):
        text = text[1:]
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if '\0' in text or not text.strip(' \t\r\n\f\v'):
        raise InvalidRequest()
    source_digest = sha256(raw).hexdigest()
    canonical_digest = sha256(text.encode('utf-8')).hexdigest()
    profile = f'cragkit.structure.bytes.v1:target={target_bytes}:max={max_chunk_bytes}'
    if token_mode:
        profile = (f'cragkit.structure.tokens.v1:target_bytes={target_bytes}:max_bytes={max_chunk_bytes}'
                   f':tokenizer={tokenizer_id}:target={token_target}:max={max_tokens}')
    calls = 0

    def count(value: str) -> int | None:
        nonlocal calls
        if not token_mode:
            return None
        calls += 1
        if calls > 65_536:
            raise InvalidRequest()
        failed = False
        result: object = None
        try:
            assert token_counter is not None
            result = token_counter(value)
        except Exception:
            failed = True
        if failed:
            raise InvalidRequest() from None
        if iscoroutine(result):
            result.close()
            raise InvalidRequest()
        return _integer(result, 0, 9_007_199_254_740_991)

    def fits(value: str, tokens: int | None, soft: bool) -> bool:
        return (len(value.encode('utf-8')) <= (target_bytes if soft else max_chunk_bytes)
                and (not token_mode or (tokens is not None and tokens <= (token_goal if soft else token_max))))

    def pieces() -> Iterator[tuple[str, bool]]:
        for block in _blocks(text, format == 'text/markdown'):
            if fits(block, count(block), False):
                yield block, False
                continue
            if not token_mode:
                parts: list[str] = []
                size = 0
                for char in block:
                    width = len(char.encode('utf-8'))
                    if parts and size + width > target_bytes:
                        yield ''.join(parts), True
                        parts = []
                        size = 0
                    parts.append(char)
                    size += width
                if parts:
                    yield ''.join(parts), True
                continue
            current = ''
            for char in block:
                candidate = current + char
                tokens = count(candidate)
                if current and not fits(candidate, tokens, True):
                    yield current, True
                    current = char
                    tokens = count(current)
                else:
                    current = candidate
                if not fits(current, tokens, False):
                    raise InvalidRequest()
            if current:
                yield current, True

    packed: list[tuple[str, bool]] = []
    packing: list[str] = []
    packing_bytes = 0
    packing_split = False
    for piece, split in pieces():
        size = len(piece.encode('utf-8'))
        combine = bool(packing) and packing_bytes + size <= target_bytes
        if combine and token_mode:
            combine = fits(''.join(packing) + piece, count(''.join(packing) + piece), True)
        if packing and not combine:
            packed.append((''.join(packing), packing_split))
            if len(packed) >= 1024:
                raise InvalidRequest()
            packing = []
            packing_bytes = 0
            packing_split = False
        packing.append(piece)
        packing_bytes += size
        packing_split = packing_split or split
    if packing:
        packed.append((''.join(packing), packing_split))
    if len(packed) > 1024:
        raise InvalidRequest()
    chunks: list[CanonicalChunk] = []
    start = 0
    for ordinal, (piece, split) in enumerate(packed):
        encoded = piece.encode('utf-8')
        end = start + len(encoded)
        tokens = count(piece)
        if not fits(piece, tokens, False):
            raise InvalidRequest()
        chunk_id = sha256(f'{canonical_digest}:{start}:{end}:{profile}'.encode('utf-8')).hexdigest()
        chunks.append(CanonicalChunk(chunk_id=chunk_id, ordinal=ordinal, start_byte=start,
            end_byte=end, text=piece, text_sha256=sha256(encoded).hexdigest(),
            oversized_split=split, token_count=tokens))
        start = end
    return CanonicalDocument(canonical_text=text, source_sha256=source_digest,
        canonical_sha256=canonical_digest,
        parser_id='cragkit.markdown.v1' if format == 'text/markdown' else 'cragkit.text.v1',
        chunker_profile=profile, format='text/markdown' if format == 'text/markdown' else 'text/plain', tokenizer_id=tokenizer_id,
        token_count=count(text), chunks=tuple(chunks))

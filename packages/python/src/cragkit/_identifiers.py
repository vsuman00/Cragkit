"""Bounded ASCII symbol profile shared by ingestion and exact lookup."""
import re

from .errors import InvalidRequest

IDENTIFIER_PROFILE = 'identifier_ascii_v1'
_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*(?:[.:/-]+[A-Za-z0-9_]+)*(?:\+\+|#)?')
_SIGNAL = re.compile(r'[0-9_.:/+\#-]|[a-z][A-Z]')


def extract_identifiers(text: str) -> tuple[str, ...]:
    return tuple(sorted({match.group() for match in _PATTERN.finditer(text)
                         if len(match.group()) <= 256 and _SIGNAL.search(match.group())},
                        key=lambda value: value.encode('utf-8')))


def validate_identifier(value: object) -> str:
    if not isinstance(value, str) or len(value) > 256 or extract_identifiers(value) != (value,):
        raise InvalidRequest()
    return value

"""Compile the supported identifier filter subset without interpolating values."""
from __future__ import annotations

from .contracts.models import EqualityFilter, Filter, GroupFilter, MembershipFilter, NotFilter
from .errors import InvalidRequest, UnsupportedCapability


def compile_filters(filters: tuple[Filter, ...]) -> tuple[str, tuple[object, ...]]:
    parameters: list[object] = []

    def compile_one(item: Filter) -> str:
        if isinstance(item, GroupFilter):
            joiner = ' AND ' if item.op == 'and' else ' OR '
            return '(' + joiner.join(compile_one(child) for child in item.filters) + ')'
        if isinstance(item, NotFilter):
            return '(NOT ' + compile_one(item.filter) + ')'
        column = {'document_id': 'd.document_id', 'revision_id': 'g.revision_id'}.get(item.field)
        if column is None:
            raise UnsupportedCapability()
        if isinstance(item, EqualityFilter):
            if not isinstance(item.value, str):
                raise UnsupportedCapability()
            if '\0' in item.value:
                raise InvalidRequest()
            parameters.append(item.value)
            operator = '=' if item.op == 'eq' else '<>'
            return f'({column} {operator} %s)'
        if isinstance(item, MembershipFilter):
            if not all(isinstance(value, str) for value in item.values):
                raise UnsupportedCapability()
            if any(isinstance(value, str) and '\0' in value for value in item.values):
                raise InvalidRequest()
            parameters.append(list(item.values))
            return f'({column} = ANY(%s::text[]))'
        raise UnsupportedCapability()

    predicate = ' AND '.join(compile_one(item) for item in filters) or 'TRUE'
    return f'COALESCE(({predicate}), FALSE)', tuple(parameters)

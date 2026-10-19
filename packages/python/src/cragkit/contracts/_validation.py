import math
from typing import Any

MAX_SAFE_NUMBER = 9_007_199_254_740_991


def text(value: str, limit: int, *, nonblank: bool = True) -> str:
    if len(value.encode("utf-8", errors="strict")) > limit:
        raise ValueError("Text exceeds byte limit")
    if nonblank and not value.strip(" \t\r\n\f\v"):
        raise ValueError("Text must be nonblank")
    return value


def identity(value: str) -> str:
    return text(value, 256)


def scalar(value: object) -> object:
    if type(value) is str:
        return text(value, 1024, nonblank=False)
    if type(value) is bool:
        return value
    return number(value)


def number(value: object) -> int | float:
    if type(value) not in (int, float):
        raise ValueError("Expected a number")
    assert isinstance(value, (int, float))
    if abs(value) > MAX_SAFE_NUMBER or not math.isfinite(value):
        raise ValueError("Expected a finite safe number")
    return value


def integer(value: object) -> object:
    if type(value) is float and math.isfinite(value) and value.is_integer():
        return int(value)
    return value


def sequence(value: object) -> tuple[Any, ...]:
    if type(value) is not list:
        raise ValueError("Expected a JSON array")
    return tuple(value)


def native_json(value: object) -> object:
    active: set[int] = set()
    stack: list[tuple[object, bool, int]] = [(value, False, 0)]
    nodes = 0
    while stack:
        item, leaving, depth = stack.pop()
        if leaving:
            active.remove(id(item))
            continue
        nodes += 1
        if nodes > 4096 or depth > 32:
            raise ValueError("Native input complexity limit exceeded")
        if type(item) in (dict, list):
            assert isinstance(item, (dict, list))
            if len(item) > 4096:
                raise ValueError("Native container limit exceeded")
            if id(item) in active:
                raise ValueError("Cyclic input")
            active.add(id(item))
            stack.append((item, True, depth))
            if isinstance(item, dict):
                if any(type(key) is not str for key in item):
                    raise ValueError("Expected string object keys")
                stack.extend((child, False, depth + 1) for child in item.values())
            else:
                assert isinstance(item, list)
                stack.extend((child, False, depth + 1) for child in item)
        elif type(item) is str:
            item.encode("utf-8", errors="strict")
        elif type(item) in (int, float):
            number(item)
        elif item is not None and type(item) is not bool:
            raise ValueError("Expected a JSON value")
    return value


def filter_roots(value: object) -> tuple[Any, ...]:
    roots = sequence(value)
    if len(roots) > 16:
        raise ValueError("Too many filter roots")
    stack: list[tuple[object, int, frozenset[int]]] = [
        (root, 1, frozenset()) for root in roots
    ]
    count = 0
    while stack:
        node, depth, ancestors = stack.pop()
        count += 1
        if count > 64 or depth > 8:
            raise ValueError("Filter complexity limit exceeded")
        if type(node) is not dict or id(node) in ancestors:
            raise ValueError("Invalid or cyclic filter")
        assert isinstance(node, dict)
        branch = ancestors | {id(node)}
        if node.get("op") in ("and", "or"):
            children = sequence(node.get("filters"))
            if not 1 <= len(children) <= 16:
                raise ValueError("Invalid group size")
            stack.extend((child, depth + 1, branch) for child in children)
        elif node.get("op") == "not":
            stack.append((node.get("filter"), depth + 1, branch))
    return roots

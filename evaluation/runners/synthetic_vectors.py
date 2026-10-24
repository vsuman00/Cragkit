"""Label-blind synthetic encoder for mechanics evaluation, never model quality."""
from hashlib import sha256
import math
import re

PROFILE = 'sha256-ascii-word-count.v1'


def encode(text: str) -> list[float]:
    values = [0.] * 1536
    for token in re.findall(r'[a-z0-9_]+', text.lower()):
        values[int.from_bytes(sha256(token.encode('ascii')).digest()[:4], 'big') % 1536] += 1.
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        values[0] = 1.
        return values
    return [value / norm for value in values]

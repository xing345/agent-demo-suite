"""Exact (sha256) and near-duplicate (simhash) detection."""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Iterable

DEFAULT_BITS = 64
TOKEN_PATTERN = re.compile(r"[a-z0-9_]+")


def simhash(text: str, *, bits: int = DEFAULT_BITS) -> int:
    tokens = TOKEN_PATTERN.findall(text.lower()) or list(text)
    weights = Counter(tokens)
    vector = [0] * bits
    for token, weight in weights.items():
        digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
        for position in range(bits):
            vector[position] += weight if (digest >> position) & 1 else -weight

    fingerprint = 0
    for position, value in enumerate(vector):
        if value > 0:
            fingerprint |= 1 << position
    return fingerprint


def hamming(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def find_near_duplicates(
    items: Iterable[tuple[str, str]],
    *,
    threshold: int = 10,
) -> list[tuple[str, str]]:
    """Flag pairs within ``threshold`` bits.

    The default suits short texts (a one-word change in a nine-word sentence
    lands around 9 bits); lower it for long documents, where 3 is typical.
    """
    fingerprints = [(item_id, simhash(text)) for item_id, text in items]
    pairs: list[tuple[str, str]] = []
    for index, (left_id, left_hash) in enumerate(fingerprints):
        for right_id, right_hash in fingerprints[index + 1 :]:
            if hamming(left_hash, right_hash) <= threshold:
                pairs.append((left_id, right_id))
    return pairs
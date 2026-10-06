"""Levenshtein alignment of expected vs heard phone sequences (section 8.1, step 6)."""

from dataclasses import dataclass
from typing import Literal

Op = Literal["match", "sub", "ins", "del"]


@dataclass(frozen=True)
class Edit:
    op: Op
    expected: str | None  # None for insertions
    heard: str | None  # None for deletions
    index: int | None  # position in the expected sequence (None for insertions)
    before: int  # for insertions: index of the expected phone it precedes (len = at the end)


def align(expected: list[str], heard: list[str]) -> list[Edit]:
    n, m = len(expected), len(heard)
    cost = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        cost[i][0] = i
    for j in range(m + 1):
        cost[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sub = 0 if expected[i - 1] == heard[j - 1] else 1
            cost[i][j] = min(cost[i - 1][j - 1] + sub, cost[i - 1][j] + 1, cost[i][j - 1] + 1)

    edits: list[Edit] = []
    i, j = n, m
    while i > 0 or j > 0:
        if i > 0 and j > 0 and cost[i][j] == cost[i - 1][j - 1] + (expected[i - 1] != heard[j - 1]):
            op: Op = "match" if expected[i - 1] == heard[j - 1] else "sub"
            edits.append(Edit(op, expected[i - 1], heard[j - 1], i - 1, i - 1))
            i, j = i - 1, j - 1
        elif i > 0 and cost[i][j] == cost[i - 1][j] + 1:
            edits.append(Edit("del", expected[i - 1], None, i - 1, i - 1))
            i -= 1
        else:
            edits.append(Edit("ins", None, heard[j - 1], None, i))
            j -= 1
    return edits[::-1]


def distance(a: list[str], b: list[str]) -> int:
    return sum(e.op != "match" for e in align(a, b))

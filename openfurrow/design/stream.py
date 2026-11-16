# SPDX-License-Identifier: Apache-2.0
"""The random stream every generated layout draws from (decision 0015).

The stream for a method and a seed is the concatenation of
SHA-256("<method>:<seed>:<counter>") for counter = 0, 1, 2, ..., read eight bytes at a
time, big-endian; integers below a bound are drawn by rejection, and a list is shuffled by
Fisher-Yates. `randomization.py` states these steps in full.
"""

from __future__ import annotations

import hashlib

_wordBytes = 8
_wordRange = 1 << (8 * _wordBytes)


class Sha256Stream:
  """The random stream of one randomization method for one seed."""

  def __init__(self, seed: int, methodName: str) -> None:
    self._seed = seed
    self._methodName = methodName
    self._counter = 0
    self._buffer = b""

  def nextWord(self) -> int:
    if len(self._buffer) < _wordBytes:
      text = f"{self._methodName}:{self._seed}:{self._counter}"
      self._buffer += hashlib.sha256(text.encode("ascii")).digest()
      self._counter += 1
    word = int.from_bytes(self._buffer[:_wordBytes], "big")
    self._buffer = self._buffer[_wordBytes:]
    return word

  def below(self, bound: int) -> int:
    limit = _wordRange - _wordRange % bound
    while True:
      word = self.nextWord()
      if word < limit:
        return word % bound


def shuffled(count: int, stream: Sha256Stream) -> list[int]:
  """0..count-1 shuffled by Fisher-Yates, from the last position down to the second."""
  order = list(range(count))
  for position in range(count - 1, 0, -1):
    chosen = stream.below(position + 1)
    order[position], order[chosen] = order[chosen], order[position]
  return order

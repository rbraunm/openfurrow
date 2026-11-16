# SPDX-License-Identifier: Apache-2.0
"""Local account passwords, hashed with the standard library's scrypt (decision 0036).

The stored form is 'scrypt$<n>$<r>$<p>$<salt>$<hash>' (base64), so the cost can rise
later without losing older hashes. A password is at least 12 characters and at most 256;
nothing else about its shape is required.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from openfurrow.identity.model import IdentityError

costN = 2 ** 15
costR = 8
costP = 1
minimumLength = 12
maximumLength = 256


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
  return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def hashPassword(password: str) -> str:
  if not minimumLength <= len(password) <= maximumLength:
    raise IdentityError(f"a password is {minimumLength} to {maximumLength} characters, got {len(password)}")
  salt = secrets.token_bytes(16)
  digest = _derive(password, salt, costN, costR, costP)
  return "$".join(["scrypt", str(costN), str(costR), str(costP),
                   base64.b64encode(salt).decode("ascii"), base64.b64encode(digest).decode("ascii")])


def passwordMatches(password: str, stored: str) -> bool:
  parts = stored.split("$")
  if len(parts) != 6 or parts[0] != "scrypt":
    raise IdentityError("a stored password hash is not in the scrypt form")
  n, r, p = (int(part) for part in parts[1:4])
  digest = _derive(password[:maximumLength], base64.b64decode(parts[4]), n, r, p)
  return hmac.compare_digest(digest, base64.b64decode(parts[5]))

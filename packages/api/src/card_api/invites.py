"""Invite codes: unguessable, typo-tolerant, and stored in one canonical form.

Sign-up is a public Cognito endpoint, so codes must resist guessing: 12 random symbols from a
32-letter alphabet is 60 bits, far beyond what anyone can enumerate against Cognito's sign-up
rate limits. The alphabet drops look-alikes (I, L, O, U) so a code read aloud or retyped still
works; input is normalized (case, spaces, dashes) before lookup.
"""

import re
import secrets

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U
PREFIX = "CA"
SYMBOLS = 12  # 12 * 5 bits = 60 bits of entropy
_GROUP = 4


def new_code() -> str:
    """A fresh code in canonical form, e.g. 'CA7K2MQ9XD4HWT'."""
    return PREFIX + "".join(secrets.choice(ALPHABET) for _ in range(SYMBOLS))


def normalize(code: str) -> str:
    """What the user typed -> canonical form: 'ca-7k2m-q9xd-4hwt ' -> 'CA7K2MQ9XD4HWT'."""
    return re.sub(r"[\s-]", "", code).upper()


def display(code: str) -> str:
    """Canonical -> readable: 'CA7K2MQ9XD4HWT' -> 'CA-7K2M-Q9XD-4HWT'."""
    if not (code.startswith(PREFIX) and len(code) == len(PREFIX) + SYMBOLS):
        return code  # e.g. the local demo code
    body = code[len(PREFIX) :]
    return "-".join([PREFIX, *(body[i : i + _GROUP] for i in range(0, SYMBOLS, _GROUP))])

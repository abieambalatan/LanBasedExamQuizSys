"""Use Django password hashes while accepting passwords saved by the Flask app."""

import hashlib
import hmac

from django.contrib.auth.hashers import check_password, make_password


def generate_password_hash(password):
    return make_password(password)


def check_password_hash(encoded, password):
    if not isinstance(encoded, str) or not isinstance(password, str):
        return False
    try:
        if encoded.startswith(("scrypt:", "pbkdf2:")):
            method, salt, expected = encoded.split("$", 2)
            parts = method.split(":")
            if parts[0] == "scrypt":
                n, r, p = map(int, parts[1:])
                actual = hashlib.scrypt(password.encode(), salt=salt.encode(), n=n, r=r, p=p, maxmem=128 * 1024 * 1024).hex()
            else:
                actual = hashlib.pbkdf2_hmac(parts[1], password.encode(), salt.encode(), int(parts[2])).hex()
            return hmac.compare_digest(actual, expected)
        return check_password(password, encoded)
    except (ValueError, TypeError, OverflowError):
        return False

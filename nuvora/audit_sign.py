# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Local HMAC checkpoint over the audit tip. Not an external WORM store."""
import hashlib
import hmac
import os
import time


def sign_tip(tip, secret=None):
    """Return a checkpoint dict for a verified tip digest, or None if no secret."""
    secret = secret if secret is not None else os.getenv('NUVORA_SECRET_KEY', '')
    if not secret or len(secret) < 32 or not tip:
        return None
    at = time.time()
    payload = f'{tip}:{int(at)}'
    signature = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {'tip': tip, 'at': at, 'alg': 'HMAC-SHA256', 'signature': signature}


def verify_checkpoint(checkpoint, secret=None):
    if not isinstance(checkpoint, dict):
        return False
    secret = secret if secret is not None else os.getenv('NUVORA_SECRET_KEY', '')
    if not secret or len(secret) < 32:
        return False
    tip = checkpoint.get('tip', '')
    at = checkpoint.get('at')
    sig = checkpoint.get('signature', '')
    if not tip or not isinstance(at, (int, float)) or not sig:
        return False
    payload = f'{tip}:{int(at)}'
    expected = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig)

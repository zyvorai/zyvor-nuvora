# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Character-based token estimates. Not a model tokenizer — a consistent budget heuristic."""


def estimate(text, chars_per_token=4):
    """Estimate tokens for a string. Uses ceil(len/chars_per_token), minimum 1 for non-empty."""
    if not text:
        return 0
    if not isinstance(text, str):
        text = str(text)
    n = len(text)
    return max(1, (n + chars_per_token - 1) // chars_per_token)


def estimate_messages(messages, chars_per_token=4):
    """Sum estimates over chat messages (string or multimodal content parts)."""
    total = 0
    for message in messages or []:
        content = message.get('content') if isinstance(message, dict) else ''
        if isinstance(content, str):
            total += estimate(content, chars_per_token)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get('type') == 'text':
                    total += estimate(part.get('text', ''), chars_per_token)
                elif isinstance(part, dict) and part.get('type') == 'image_url':
                    total += 85  # rough vision placeholder
                else:
                    total += estimate(str(part), chars_per_token)
        else:
            total += estimate(str(content or ''), chars_per_token)
    return total


def estimate_texts(texts, chars_per_token=4):
    return sum(estimate(t, chars_per_token) for t in texts or [])

"""API key masking utilities for safe logging and response display."""


def mask_api_key(key: str) -> str:
    """Mask an API key for safe display.

    Args:
        key: The API key to mask.

    Returns:
        Masked key showing first 4 and last 4 chars, middle replaced with dots.
        If key is <= 8 chars, returns all dots.
    """
    if not key:
        return ""
    if len(key) <= 8:
        return "•" * len(key)
    return f"{key[:4]}{'•' * 8}{key[-4:]}"

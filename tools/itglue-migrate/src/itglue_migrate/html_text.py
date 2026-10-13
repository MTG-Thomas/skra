"""Bounded, linear helpers for classifying exported HTML content."""

MAX_HTML_SCAN_CHARS = 4 * 1024 * 1024


def has_visible_html_text(content: str | None) -> bool:
    """Return whether bounded HTML-like input contains non-whitespace text.

    This preserves the old tag-stripping semantics without a backtracking
    regular expression. Oversized input is treated as non-empty so validation
    never discards content it did not inspect.
    """
    if not content:
        return False
    if len(content) > MAX_HTML_SCAN_CHARS:
        return True

    in_tag = False
    for char in content:
        if char == "<":
            in_tag = True
        elif char == ">" and in_tag:
            in_tag = False
        elif not in_tag and not char.isspace():
            return True
    # Match the prior tag-stripping behavior for an unterminated ``<...``:
    # without a closing ``>``, it is text rather than a removable tag.
    return in_tag

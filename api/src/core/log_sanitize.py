"""
Log Injection Protection (CWE-117).

Provides a sanitizer for values interpolated into log messages. Log entries
built from user-controlled data allow forged log lines unless carriage
returns and line feeds are stripped.
"""

from typing import Any


def sanitize_log_value(value: Any) -> str:
    """
    Make a value safe for inclusion in a log message.

    Converts the value to text and strips carriage returns and line feeds
    so it cannot inject forged entries into line-oriented logs.

    Args:
        value: The value to sanitize (any type; stringified).

    Returns:
        The stringified value with CR/LF characters removed.
    """
    return str(value).replace("\r", "").replace("\n", "")

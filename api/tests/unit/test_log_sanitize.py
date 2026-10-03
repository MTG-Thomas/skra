"""Tests for the CWE-117 log injection sanitizer."""

from src.core.log_sanitize import sanitize_log_value


def test_strips_newlines_and_carriage_returns():
    assert sanitize_log_value("ok\ninjected\r\nline") == "okinjectedline"


def test_stringifies_non_string_values():
    assert sanitize_log_value(123) == "123"
    assert sanitize_log_value(None) == "None"
    assert sanitize_log_value(True) == "True"


def test_leaves_clean_values_unchanged():
    assert sanitize_log_value("plain message 123") == "plain message 123"
    assert sanitize_log_value("") == ""

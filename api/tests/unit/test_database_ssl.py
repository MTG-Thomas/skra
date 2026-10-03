"""Tests for asyncpg sslmode handling in database URL preparation.

Pins the sslmode -> connect_args mapping used by get_engine, so the
production guard (issue #131, see test_production_guards.py) and the
runtime mapping cannot drift apart silently.
"""

import ssl

from src.core.database import _prepare_asyncpg_url

BASE_URL = "postgresql+asyncpg://skra:secret@db:5432/skra"


def test_require_disables_verification_for_non_production_use():
    """require keeps its legacy meaning: encrypted but unverified.

    Production never reaches this branch (Settings rejects require),
    but dev/test runs against managed databases still rely on it.
    """
    cleaned, connect_args = _prepare_asyncpg_url(BASE_URL + "?sslmode=require")

    assert "sslmode" not in cleaned
    assert connect_args["ssl"].verify_mode is ssl.CERT_NONE
    assert connect_args["ssl"].check_hostname is False


def test_verify_ca_requires_cert_but_skips_hostname():
    cleaned, connect_args = _prepare_asyncpg_url(BASE_URL + "?sslmode=verify-ca")

    assert "sslmode" not in cleaned
    assert connect_args["ssl"].verify_mode is ssl.CERT_REQUIRED
    assert connect_args["ssl"].check_hostname is False


def test_verify_full_verifies_cert_and_hostname():
    cleaned, connect_args = _prepare_asyncpg_url(BASE_URL + "?sslmode=verify-full")

    assert "sslmode" not in cleaned
    assert connect_args["ssl"].verify_mode is ssl.CERT_REQUIRED
    assert connect_args["ssl"].check_hostname is True


def test_prefer_and_absent_sslmode_need_no_context():
    _, prefer_args = _prepare_asyncpg_url(BASE_URL + "?sslmode=prefer")
    assert prefer_args == {"ssl": "prefer"}

    cleaned, connect_args = _prepare_asyncpg_url(BASE_URL)
    assert cleaned == BASE_URL
    assert connect_args == {}


def test_other_query_params_survive_sslmode_extraction():
    cleaned, _ = _prepare_asyncpg_url(BASE_URL + "?sslmode=verify-full&timeout=10")

    assert "sslmode" not in cleaned
    assert "timeout=10" in cleaned

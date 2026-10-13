"""Configure ZAP authentication without putting the bearer token on its command line."""

import os


def zap_started(zap, _target):
    """Add the Authorization header after the ZAP API becomes available."""
    authorization = os.environ.get("ZAP_AUTH_HEADER_VALUE")
    if not authorization:
        raise RuntimeError("ZAP_AUTH_HEADER_VALUE is required")

    zap.replacer.add_rule(
        description="auth-header",
        enabled=True,
        matchtype="REQ_HEADER",
        matchregex=False,
        matchstring="Authorization",
        replacement=authorization,
    )

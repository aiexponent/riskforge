"""Blocks network sockets in Python processes started by the test suite.

tests/rf_testkit.py puts this directory first on PYTHONPATH, so every riskforge
subprocess imports it at start-up. Unix sockets stay allowed because asyncio's event
loop needs a socketpair.
"""

import pytest_socket

pytest_socket.disable_socket(allow_unix_socket=True)

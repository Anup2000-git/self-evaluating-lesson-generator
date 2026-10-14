"""Test-wide defaults (loaded before every package's tests).

Tests never send traces: a developer's .env may hold real Langfuse keys, and environment
variables take precedence over .env. Tests that exercise tracing build their own settings.
"""

import os

os.environ["LANGFUSE_TRACING_ENABLED"] = "false"

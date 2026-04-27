# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
from datetime import datetime
from types import SimpleNamespace

from tools.common import DateTimeEncoder, get_session_context, mask_sensitive_data


def test_mask_sensitive_data_masks_all_but_last_eight_characters():
    masked = mask_sensitive_data({"api_key": "1234567890abcdef"})
    assert masked["api_key"] == "********90abcdef"


def test_mask_sensitive_data_keeps_short_api_key_unmodified():
    masked = mask_sensitive_data({"api_key": "short"})
    assert masked["api_key"] == "short"


def test_get_session_context_returns_fastmcp_session_context():
    expected = SimpleNamespace(name="session")
    ctx = SimpleNamespace(fastmcp=SimpleNamespace(session_context=expected))
    assert get_session_context(ctx) is expected


def test_datetime_encoder_serializes_datetime_to_isoformat():
    payload = {"when": datetime(2026, 1, 2, 3, 4, 5)}
    encoded = json.dumps(payload, cls=DateTimeEncoder)
    assert "2026-01-02T03:04:05" in encoded

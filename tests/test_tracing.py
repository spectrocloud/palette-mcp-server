# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import tracing


def test_create_span_returns_noop_context_when_tracer_is_unavailable(monkeypatch):
    monkeypatch.setattr(tracing, "tracer", None, raising=True)
    with tracing.create_span("test-span") as span:
        assert span is None


def test_safe_setters_do_not_raise_when_tracer_or_span_is_missing(monkeypatch):
    monkeypatch.setattr(tracing, "tracer", None, raising=True)
    tracing.safe_set_tool(None, "name", "desc", {})
    tracing.safe_set_input(None, {"a": 1})
    tracing.safe_set_output(None, {"b": 2})
    tracing.safe_set_status(None, "ok")
    tracing.safe_set_span_status(None, "OK")


def test_set_tool_metadata_and_set_span_data_gracefully_handle_missing_methods():
    class SpanWithoutMethods:
        pass

    span = SpanWithoutMethods()
    tracing.set_tool_metadata(span, "name", "desc", {})
    tracing.set_span_data(
        span, input_data={"a": 1}, output_data={"b": 2}, status=("ok",)
    )

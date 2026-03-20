# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import json
import os
from contextlib import nullcontext

# Only import and setup OpenTelemetry if Phoenix is configured.
if os.environ.get("PHOENIX_COLLECTOR_ENDPOINT"):
    from opentelemetry import trace

    tracer = trace.get_tracer(__name__)
else:
    tracer = None


def create_span(name: str):
    """Create a tracing span or return a no-op context manager."""
    if tracer is None:
        return nullcontext()

    try:
        return tracer.start_as_current_span(
            name, openinference_span_kind="tool", set_status_on_exception=False
        )
    except (TypeError, AttributeError):
        try:
            return tracer.start_as_current_span(name)
        except (TypeError, AttributeError):
            return nullcontext()


def safe_set_tool(span, name: str, description: str, parameters: dict):
    """Safely set tool attributes, no-op if tracing is unavailable."""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_tool"):
            span.set_tool(name=name, description=description, parameters=parameters)
    except Exception:
        pass


def safe_set_input(span, data: dict):
    """Safely set input attributes, no-op if tracing is unavailable."""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_input"):
            span.set_input(data)
    except Exception:
        pass


def safe_set_output(span, data: dict):
    """Safely set output attributes, no-op if tracing is unavailable."""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_output"):
            span.set_output(data)
    except Exception:
        pass


def safe_set_status(span, status):
    """Safely set status, no-op if tracing is unavailable."""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, "set_status"):
            span.set_status(status)
    except Exception:
        pass


def safe_set_span_status(span, status_code: str, description: str = None):
    """Safely set span status without hard dependency when tracing is unavailable."""
    if span is None:
        return
    try:
        from opentelemetry import trace

        if status_code == "OK":
            safe_set_status(span, trace.Status(trace.StatusCode.OK))
        elif status_code == "ERROR":
            safe_set_status(
                span, trace.Status(trace.StatusCode.ERROR, description or "")
            )
    except ImportError:
        pass


def set_tool_metadata(span, name: str, description: str, parameters: dict):
    """Set tool metadata with graceful error handling."""
    try:
        span.set_tool(name=name, description=description, parameters=parameters)
    except (TypeError, AttributeError):
        pass


def set_span_data(
    span, input_data: dict = None, output_data: dict = None, status: tuple = None
):
    """Set span input/output/status with graceful error handling."""
    try:
        if input_data is not None:
            span.set_input(json.dumps(input_data))
    except (TypeError, AttributeError):
        pass

    try:
        if output_data is not None:
            span.set_output(json.dumps(output_data))
    except (TypeError, AttributeError):
        pass

    try:
        if status is not None:
            span.set_status(status)
    except (TypeError, AttributeError):
        pass

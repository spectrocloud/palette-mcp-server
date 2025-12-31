# Copyright (c) Spectro Cloud
# SPDX-License-Identifier: Apache-2.0

import tempfile
import os
import json
import glob
import signal
import sys
from contextlib import nullcontext

# Only import and setup OpenTelemetry if Phoenix is configured
if os.environ.get('PHOENIX_COLLECTOR_ENDPOINT'):
    from opentelemetry import trace
    tracer = trace.get_tracer(__name__)
else:
    tracer = None

def write_kubeconfig_to_temp(cluster_uid: str, kubeconfig_content: str, is_admin: bool = False) -> str:
    """Helper function to write kubeconfig content to a temporary file.
    
    Args:
        cluster_uid (str): The UID of the cluster to use in the filename
        kubeconfig_content (str): The kubeconfig content to write
        is_admin (bool): Whether this is an admin kubeconfig (adds .admin to filename)
        
    Returns:
        str: Path to the written kubeconfig file
    """
    temp_dir = tempfile.gettempdir()
    kubeconfig_dir = os.path.join(temp_dir, "kubeconfig")
    os.makedirs(kubeconfig_dir, exist_ok=True)
    
    if is_admin:
        filename = f"{cluster_uid}.admin.kubeconfig"
    else:
        filename = f"{cluster_uid}.kubeconfig"
    
    kubeconfig_path = os.path.join(kubeconfig_dir, filename)
    with open(kubeconfig_path, 'w') as f:
        f.write(kubeconfig_content)
    return kubeconfig_path


def cleanup_temp_files():
    """Clean up temporary kubeconfig files created by the server"""
    try:
        temp_dir = tempfile.gettempdir()
        cleaned_count = 0
        
        # Clean up kubeconfig files in the subdirectory (current version)
        kubeconfig_dir = os.path.join(temp_dir, "kubeconfig")
        if os.path.exists(kubeconfig_dir):
            kubeconfig_pattern = os.path.join(kubeconfig_dir, "*.kubeconfig")
            kubeconfig_files = glob.glob(kubeconfig_pattern)
            
            for file_path in kubeconfig_files:
                try:
                    os.remove(file_path)
                    cleaned_count += 1
                except OSError:
                    # File might already be deleted or in use, skip silently
                    pass
        
        # Clean up legacy kubeconfig files directly in temp directory (previous version)
        legacy_pattern = os.path.join(temp_dir, "*.kubeconfig")
        legacy_files = glob.glob(legacy_pattern)
        
        for file_path in legacy_files:
            try:
                os.remove(file_path)
                cleaned_count += 1
            except OSError:
                # File might already be deleted or in use, skip silently
                pass
        
        if cleaned_count > 0:
            print(f"🧹 Cleaned up {cleaned_count} temporary kubeconfig file(s)")
        else:
            print("🧹 No temporary kubeconfig files to clean up")
    except Exception:
        # Cleanup should never fail the shutdown process
        pass


def create_signal_handler(logger=None):
    """Create a signal handler function for graceful shutdown.
    
    Args:
        logger: Optional logger instance. If None, uses print statements.
        
    Returns:
        function: Signal handler function
    """
    # Track if we've already handled a signal to avoid multiple shutdowns
    shutdown_initiated = False
    
    def signal_handler(signum, frame):
        """Handle shutdown signals gracefully"""
        nonlocal shutdown_initiated
        
        # Avoid handling multiple signals
        if shutdown_initiated:
            return
        shutdown_initiated = True
        
        signal_name = "SIGINT (Ctrl+C)" if signum == signal.SIGINT else "SIGTERM"
        
        if logger:
            logger.info(f"Received {signal_name} signal")
            logger.info("Shutting down Palette MCP Server gracefully...")
        else:
            print(f"\n🛑 Received {signal_name} signal")
            print("🔄 Shutting down Palette MCP Server gracefully...")
        
        # Perform cleanup
        cleanup_temp_files()
        
        if logger:
            logger.info("Palette MCP Server stopped")
        else:
            print("✅ Palette MCP Server stopped")
        
        # Use os._exit to avoid threading issues during shutdown
        # This bypasses Python's normal shutdown process which can hang
        # with threading and stdio conflicts
        os._exit(0)
    
    return signal_handler


def create_span(name: str):
    """Helper function to create a span or return a no-op context manager"""
    if tracer is None:
        # Phoenix not configured, return a no-op context manager
        return nullcontext()
    
    try:
        # Try Phoenix-style span first
        return tracer.start_as_current_span(
            name,
            openinference_span_kind="tool",
            set_status_on_exception=False
        )
    except (TypeError, AttributeError):
        # Phoenix attributes not supported, try basic span
        try:
            return tracer.start_as_current_span(name)
        except (TypeError, AttributeError):
            # Even basic span doesn't work, return no-op
            return nullcontext()

def safe_set_tool(span, name: str, description: str, parameters: dict):
    """Safely set tool attributes, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, 'set_tool'):
            span.set_tool(name=name, description=description, parameters=parameters)
    except:
        pass

def safe_set_input(span, data: dict):
    """Safely set input attributes, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, 'set_input'):
            span.set_input(data)
    except:
        pass

def safe_set_output(span, data: dict):
    """Safely set output attributes, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, 'set_output'):
            span.set_output(data)
    except:
        pass

def safe_set_status(span, status):
    """Safely set status, no-op if Phoenix not configured"""
    if tracer is None or span is None:
        return
    try:
        if hasattr(span, 'set_status'):
            span.set_status(status)
    except:
        pass

def set_tool_metadata(span, name: str, description: str, parameters: dict):
    """Helper function to set tool metadata with error handling"""
    try:
        span.set_tool(
            name=name,
            description=description,
            parameters=parameters
        )
    except (TypeError, AttributeError):
        pass

def set_span_data(span, input_data: dict = None, output_data: dict = None, status: tuple = None):
    """Helper function to set span input/output data and status with error handling"""
    try:
        if input_data is not None:
            # Convert input data to string to ensure valid type
            span.set_input(json.dumps(input_data))
    except (TypeError, AttributeError):
        pass

    try:
        if output_data is not None:
            # Convert output data to string to ensure valid type
            span.set_output(json.dumps(output_data))
    except (TypeError, AttributeError):
        pass

    try:
        if status is not None:
            span.set_status(status)
    except (TypeError, AttributeError):
        pass

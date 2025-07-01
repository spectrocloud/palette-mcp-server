import tempfile
import os
import json
import glob
import signal
import sys
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

def write_kubeconfig_to_temp(cluster_uid: str, kubeconfig_content: str) -> str:
    """Helper function to write kubeconfig content to a temporary file.
    
    Args:
        cluster_uid (str): The UID of the cluster to use in the filename
        kubeconfig_content (str): The kubeconfig content to write
        
    Returns:
        str: Path to the written kubeconfig file
    """
    temp_dir = tempfile.gettempdir()
    kubeconfig_path = os.path.join(temp_dir, f"{cluster_uid}.kubeconfig")
    with open(kubeconfig_path, 'w') as f:
        f.write(kubeconfig_content)
    return kubeconfig_path


def cleanup_temp_files():
    """Clean up temporary kubeconfig files created by the server"""
    try:
        temp_dir = tempfile.gettempdir()
        # Find all kubeconfig files created by this server
        kubeconfig_pattern = os.path.join(temp_dir, "*.kubeconfig")
        kubeconfig_files = glob.glob(kubeconfig_pattern)
        
        cleaned_count = 0
        for file_path in kubeconfig_files:
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


# Add this helper function near the top, after the tracer definition
def create_span(name: str):
    """Helper function to create a span with fallback for unsupported parameters"""
    # Check if we're running in MCP Inspector
    if os.environ.get('MCP_INSPECTOR', '').lower() == 'true':
        # We're in MCP Inspector, use basic span
        return tracer.start_as_current_span(name)
    else:
        # We're in the tool context, use tool span
        try:
            return tracer.start_as_current_span(
                name,
                openinference_span_kind="tool",
                set_status_on_exception=False
            )
        except (TypeError, AttributeError):
            return tracer.start_as_current_span(name)

# Add this helper function to check if we can set tool attributes
def can_set_openinference_attributes(span) -> bool:
    """Check if the span supports OpenInference attributes"""
    return not os.environ.get('MCP_INSPECTOR', '').lower() == 'true' and hasattr(span, '_is_openinference_span')

def safe_set_tool(span, name: str, description: str, parameters: dict):
    """Safely set tool attributes, failing silently"""
    try:
        span.set_tool(name=name, description=description, parameters=parameters)
    except:
        pass

def safe_set_input(span, data: dict):
    """Safely set input attributes, failing silently"""
    try:
        span.set_input(data)
    except:
        pass

def safe_set_output(span, data: dict):
    """Safely set output attributes, failing silently"""
    try:
        span.set_output(data)
    except:
        pass

def safe_set_status(span, status):
    """Safely set status, failing silently"""
    try:
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

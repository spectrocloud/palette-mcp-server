import json
import yaml
import logging
import os





# yaml_file_to_json_file is a helper function to convert a YAML file to a JSON file
def yaml_file_to_json_file(yaml_file_path, json_file_path, logger: logging.Logger):
    import datetime
    
    def convert_datetime(obj):
        """Convert datetime objects to ISO format strings"""
        if isinstance(obj, dict):
            return {k: convert_datetime(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [convert_datetime(item) for item in obj]
        elif isinstance(obj, datetime.datetime):
            return obj.isoformat()
        elif isinstance(obj, datetime.date):
            return obj.isoformat()
        else:
            return obj
    
    def remove_v1_prefixes(obj):
        """Remove v1 and V1 prefixes from operationId values"""
        if isinstance(obj, dict):
            result = {}
            for key, value in obj.items():
                if key == 'operationId' and isinstance(value, str):
                    # Remove v1 or V1 prefix from operationId
                    if value.startswith('v1'):
                        result[key] = value[2:]
                    elif value.startswith('V1'):
                        result[key] = value[2:]
                    else:
                        result[key] = value
                else:
                    result[key] = remove_v1_prefixes(value)
            return result
        elif isinstance(obj, list):
            return [remove_v1_prefixes(item) for item in obj]
        else:
            return obj
    
    with open(yaml_file_path, 'r') as yaml_file:
        yaml_data = yaml.safe_load(yaml_file)
    
    # Convert datetime objects to strings
    json_data = convert_datetime(yaml_data)
    
    # Note: v1 prefixes are now removed dynamically using mcp_component_fn
    
    with open(json_file_path, 'w') as json_file:
        json.dump(json_data, json_file, indent=2)

# load_openapi_spec is a helper function to load an OpenAPI spec from a file
def load_openapi_spec(file_path: str, logger: logging.Logger) -> dict:
    """Load and parse an OpenAPI specification from a YAML or JSON file."""
    
    # Smart path resolution - try multiple possible locations
    def find_openapi_file(path: str) -> str:
        """Try to find the OpenAPI file in multiple locations."""
        possible_paths = []
        
        # Get the directory where this script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Try the path as provided
        possible_paths.append(path)
        
        # Try relative to the script directory
        possible_paths.append(os.path.join(script_dir, path))
        
        # Try relative to the parent directory of the script
        parent_dir = os.path.dirname(script_dir)
        possible_paths.append(os.path.join(parent_dir, path))
        
        # If path doesn't start with a path separator, try some common patterns
        if not path.startswith(('/', './')):
            # Try as if we're in the project root
            possible_paths.append(os.path.join(parent_dir, path))
            # Try with explicit openapi/ prefix if not already there
            if not path.startswith('openapi/'):
                possible_paths.append(os.path.join(parent_dir, 'openapi', os.path.basename(path)))
        
        # Try each possible path
        for possible_path in possible_paths:
            if os.path.exists(possible_path):
                logger.info(f"Found OpenAPI spec at: {possible_path}")
                return possible_path
        
        # If none found, raise error with helpful message
        logger.error(f"OpenAPI spec not found. Tried paths: {possible_paths}")
        raise FileNotFoundError(f"OpenAPI spec not found at any of: {possible_paths}")
    
    # Find the actual file path
    actual_file_path = find_openapi_file(file_path)
    
    # Convert YAML to JSON if needed
    if actual_file_path.endswith('.yaml') or actual_file_path.endswith('.yml'):
        json_file_path = actual_file_path.replace('.yaml', '.json').replace('.yml', '.json')
        yaml_file_to_json_file(actual_file_path, json_file_path, logger)
        actual_file_path = json_file_path
    
    with open(actual_file_path, 'r') as f:
        spec = json.load(f)
        fix_exclusive_minimums(spec, logger)
        
        # Remove components section to avoid circular references
        if 'components' in spec:
            logger.info("Removing components section to avoid circular references")
            del spec['components']
        
        # Clean up all schema references in paths but preserve required fields
        def remove_schema_references(obj):
            """Recursively remove schema references but keep required OpenAPI fields"""
            if isinstance(obj, dict):
                # Remove problematic keys that reference schemas but preserve responses
                keys_to_remove = []
                for key, value in obj.items():
                    if key in ['requestBody', 'content', 'schema', '$ref']:
                        keys_to_remove.append(key)
                    elif isinstance(value, (dict, list)):
                        remove_schema_references(value)
                
                for key in keys_to_remove:
                    del obj[key]
                    
            elif isinstance(obj, list):
                for item in obj:
                    remove_schema_references(item)
        
        # Ensure all operations have required responses field
        def ensure_responses(obj):
            """Ensure all operations have a minimal responses field"""
            if isinstance(obj, dict):
                # Check if this is an operation (has operationId or is under an HTTP method)
                if 'operationId' in obj and 'responses' not in obj:
                    obj['responses'] = {
                        '200': {
                            'description': 'Successful response'
                        },
                        'default': {
                            'description': 'Error response'
                        }
                    }
                
                # Recursively process nested objects
                for value in obj.values():
                    if isinstance(value, (dict, list)):
                        ensure_responses(value)
                        
            elif isinstance(obj, list):
                for item in obj:
                    ensure_responses(item)
        
        # Use all paths from the OpenAPI spec but clean them up
        if 'paths' in spec:
            paths = spec['paths']
            
            # First ensure all operations have responses
            ensure_responses(paths)
            
            # Then remove schema references
            remove_schema_references(paths)
            
            total_routes = sum(len([m for m in methods.keys() if m.lower() in ['get', 'post', 'put', 'delete', 'patch', 'head', 'options']]) for methods in paths.values())
            logger.info(f"Using full OpenAPI spec with {len(paths)} paths and approximately {total_routes} routes (cleaned up)")
        
        return spec

def fix_exclusive_minimums(schema, logger: logging.Logger):
    """Recursively remove or patch invalid exclusiveMinimum values."""
    if isinstance(schema, dict):
        keys = list(schema.keys())
        for key in keys:
            value = schema[key]
            if key == "exclusiveMinimum":
                if value in [0, False, True]:
                    # Fix: remove or change as needed
                    logger.info(f"Removed invalid exclusiveMinimum: {value}")
                    del schema[key]
            else:
                fix_exclusive_minimums(value, logger)
    elif isinstance(schema, list):
        for item in schema:
            fix_exclusive_minimums(item, logger)
            
            
# generate_mcp_names is a helper function to generate a mapping of tool names to remove v1 prefixes
def generate_mcp_names(openapi_spec: dict, logger: logging.Logger) -> dict:
    """Generate mcp_names mapping to remove v1 prefixes from tool names."""
    mcp_names = {}
    
    if 'paths' not in openapi_spec:
        return mcp_names
    
    for path, methods in openapi_spec['paths'].items():
        for method, operation in methods.items():
            if method.lower() in ['get', 'post', 'put', 'delete', 'patch', 'head', 'options']:
                operation_id = operation.get('operationId')
                if operation_id and (operation_id.startswith('v1') or operation_id.startswith('V1')):
                    clean_name = operation_id[2:]  # Remove v1/V1 prefix
                    mcp_names[operation_id] = clean_name
                    logger.info(f"Will rename tool: {operation_id} -> {clean_name}")
    
    return mcp_names
#!/usr/bin/env python3
"""
Python API Documentation Generator
Parses @api comments from Python files and generates Bootstrap HTML docs
"""

import re
import os
import json
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any
from jinja2 import Template

@dataclass
class ApiEndpoint:
    method: str = ""
    url: str = ""
    title: str = ""
    name: str = ""
    group: str = "General"
    group_order: int = 999  # Default to high number (low priority)
    group_doc_order: int = 999  # Default to high number (low priority) for sidebar ordering
    description: str = ""
    params: List[Dict[str, Any]] = field(default_factory=list)
    query: List[Dict[str, Any]] = field(default_factory=list)
    success: List[Dict[str, Any]] = field(default_factory=list)
    error: List[Dict[str, Any]] = field(default_factory=list)
    example: str = ""
    example_request: str = ""
    example_response: str = ""

def prettify_json(text: str) -> str:
    """Attempt to prettify JSON content in the text"""
    if not text or not text.strip():
        return text
    
    # First, try to parse the entire text as JSON
    stripped_text = text.strip()
    try:
        json_obj = json.loads(stripped_text)
        return json.dumps(json_obj, indent=2, ensure_ascii=False)
    except (json.JSONDecodeError, ValueError):
        pass
    
    # If that fails, try to find JSON blocks within the text
    lines = text.split('\n')
    prettified_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        stripped_line = line.strip()
        
        # Look for the start of a JSON object or array
        if stripped_line.startswith('{') or stripped_line.startswith('['):
            # Try to collect a complete JSON block
            json_lines = [stripped_line]
            brace_count = stripped_line.count('{') - stripped_line.count('}')
            bracket_count = stripped_line.count('[') - stripped_line.count(']')
            
            j = i + 1
            while j < len(lines) and (brace_count > 0 or bracket_count > 0):
                next_line = lines[j].strip()
                json_lines.append(next_line)
                brace_count += next_line.count('{') - next_line.count('}')
                bracket_count += next_line.count('[') - next_line.count(']')
                j += 1
            
            # Try to parse and prettify the collected JSON block
            json_block = '\n'.join(json_lines)
            try:
                json_obj = json.loads(json_block)
                prettified = json.dumps(json_obj, indent=2, ensure_ascii=False)
                prettified_lines.append(prettified)
                i = j  # Skip the lines we just processed
                continue
            except (json.JSONDecodeError, ValueError):
                # If parsing failed, just add the original line
                prettified_lines.append(line)
        else:
            prettified_lines.append(line)
        
        i += 1
    
    return '\n'.join(prettified_lines)

class ApiDocParser:
    def __init__(self):
        self.patterns = {
            'api': re.compile(r'@api\s*\{(\w+)\}\s*([^\s]+)\s*(.*)'),
            'apiName': re.compile(r'@apiName\s+(.*)'),
            'apiGroup': re.compile(r'@apiGroup\s+(.*)'),
            'apiGroupOrder': re.compile(r'@apiGroupOrder\s+(\d+)'),
            'apiGroupDocOrder': re.compile(r'@apiGroupDocOrder\s+(\d+)'),
            'apiDescription': re.compile(r'@apiDescription\s+(.*)'),
            'apiParam': re.compile(r'@apiParam\s*\{([^}]+)\}\s*(\[?[\w.:]+\]?)\s*(.*)'),
            'apiQuery': re.compile(r'@apiQuery\s*\{([^}]+)\}\s*(\[?[\w.:]+\]?)\s*(.*)'),
            'apiSuccess': re.compile(r'@apiSuccess\s*\((\d+)\)\s*\{([^}]+)\}\s*(\w+)?\s*(.*)'),
            'apiError': re.compile(r'@apiError\s*\((\d+)\)\s*\{([^}]+)\}\s*(.*)'),
            'apiExample': re.compile(r'@apiExample\s*\{([^}]+)\}\s*(.*)'),
            'apiExampleRequest': re.compile(r'@apiExampleRequest\s*\{([^}]+)\}\s*(.*)'),
            'apiExampleResponse': re.compile(r'@apiExampleResponse\s*\{([^}]+)\}\s*(.*)'),
        }
    
    def parse_file(self, file_path: Path) -> List[ApiEndpoint]:
        """Parse a single Python file for @api comments"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            print(f"Error reading {file_path}: {e}")
            return []
        
        endpoints = []
        current_endpoint = None
        in_multiline_example = False
        in_multiline_request = False
        in_multiline_response = False
        example_lines = []
        request_lines = []
        response_lines = []
        
        for line in content.split('\n'):
            line_stripped = line.strip()
            
            # Handle multiline examples, requests, and responses
            if in_multiline_example or in_multiline_request or in_multiline_response:
                # Check if this line starts a new example type or exits multiline mode
                should_exit_multiline = False
                
                if line_stripped.startswith('@apiExampleRequest'):
                    # Finalize current multiline block and start request
                    should_exit_multiline = True
                elif line_stripped.startswith('@apiExampleResponse'):
                    # Finalize current multiline block and start response
                    should_exit_multiline = True
                elif line_stripped.startswith('@apiExample'):
                    # Finalize current multiline block and start example
                    should_exit_multiline = True
                elif line_stripped.startswith('@api') and not any(x in line_stripped for x in ['@apiExample', '@apiExampleRequest', '@apiExampleResponse']):
                    # Exit multiline mode for any other @api directive
                    should_exit_multiline = True
                
                if should_exit_multiline:
                    # Finalize any active multiline blocks
                    if in_multiline_example and current_endpoint and example_lines:
                        current_endpoint.example = '\n'.join(example_lines)
                    if in_multiline_request and current_endpoint and request_lines:
                        current_endpoint.example_request = '\n'.join(request_lines)
                    if in_multiline_response and current_endpoint and response_lines:
                        raw_response = '\n'.join(response_lines)
                        current_endpoint.example_response = prettify_json(raw_response)
                    
                    # Reset all multiline states
                    in_multiline_example = False
                    in_multiline_request = False
                    in_multiline_response = False
                    example_lines = []
                    request_lines = []
                    response_lines = []
                    
                    # If this is still an example directive, continue processing it
                    if not (line_stripped.startswith('@apiExample') or line_stripped.startswith('@apiExampleRequest') or line_stripped.startswith('@apiExampleResponse')):
                        # This is a different @api directive, let it be processed normally
                        pass
                    # If it's an example directive, it will be processed below
                else:
                    # For multiline blocks, preserve the content more liberally
                    # Remove leading comment markers but preserve structure
                    clean_line = re.sub(r'^\s*[#*/]*\s?', '', line)
                    # Add the line if it has content or if it's an empty line (for formatting)
                    if clean_line or not line_stripped:
                        if in_multiline_example:
                            example_lines.append(clean_line)
                        elif in_multiline_request:
                            request_lines.append(clean_line)
                        elif in_multiline_response:
                            response_lines.append(clean_line)
                    continue
            
            # Skip non-comment lines
            if not any(marker in line_stripped for marker in ['@api', '#', '*', '//']):
                continue
            
            # Extract @api patterns
            for pattern_name, pattern in self.patterns.items():
                match = pattern.search(line_stripped)
                if match:
                    if pattern_name == 'api':
                        # Start new endpoint
                        if current_endpoint:
                            endpoints.append(current_endpoint)
                        current_endpoint = ApiEndpoint()
                        current_endpoint.method = match.group(1).lower()
                        current_endpoint.url = match.group(2)
                        current_endpoint.title = match.group(3).strip()
                        
                    elif current_endpoint:
                        if pattern_name == 'apiName':
                            current_endpoint.name = match.group(1)
                        elif pattern_name == 'apiGroup':
                            current_endpoint.group = match.group(1)
                        elif pattern_name == 'apiGroupOrder':
                            current_endpoint.group_order = int(match.group(1))
                        elif pattern_name == 'apiGroupDocOrder':
                            current_endpoint.group_doc_order = int(match.group(1))
                        elif pattern_name == 'apiDescription':
                            current_endpoint.description = match.group(1)
                        elif pattern_name == 'apiParam':
                            param_type = match.group(1)
                            param_name = match.group(2).strip('[]')
                            param_desc = match.group(3)
                            optional = '[' in match.group(2)
                            current_endpoint.params.append({
                                'type': param_type,
                                'name': param_name,
                                'description': param_desc,
                                'optional': optional
                            })
                        elif pattern_name == 'apiQuery':
                            param_type = match.group(1)
                            param_name = match.group(2).strip('[]')
                            param_desc = match.group(3)
                            optional = '[' in match.group(2)
                            current_endpoint.query.append({
                                'type': param_type,
                                'name': param_name,
                                'description': param_desc,
                                'optional': optional
                            })
                        elif pattern_name == 'apiSuccess':
                            status_code = match.group(1)
                            response_type = match.group(2)
                            response_name = match.group(3) or 'response'
                            response_desc = match.group(4)
                            current_endpoint.success.append({
                                'status': status_code,
                                'type': response_type,
                                'name': response_name,
                                'description': response_desc
                            })
                        elif pattern_name == 'apiError':
                            status_code = match.group(1)
                            error_type = match.group(2)
                            error_desc = match.group(3)
                            current_endpoint.error.append({
                                'status': status_code,
                                'type': error_type,
                                'description': error_desc
                            })
                        elif pattern_name == 'apiExample':
                            in_multiline_example = True
                            # Skip the "{curl} Example usage:" header line
                            example_lines = []
                        elif pattern_name == 'apiExampleRequest':
                            in_multiline_request = True
                            # Skip the "{curl} Request:" header line
                            request_lines = []
                        elif pattern_name == 'apiExampleResponse':
                            in_multiline_response = True
                            # Skip the "{json} Response:" header line  
                            response_lines = []
                    break
        
        # Don't forget the last endpoint
        if current_endpoint:
            if in_multiline_example and example_lines:
                current_endpoint.example = '\n'.join(example_lines)
            if in_multiline_request and request_lines:
                current_endpoint.example_request = '\n'.join(request_lines)
            if in_multiline_response and response_lines:
                raw_response = '\n'.join(response_lines)
                current_endpoint.example_response = prettify_json(raw_response)
            endpoints.append(current_endpoint)
        
        return endpoints
    
    def parse_directory(self, directory: Path) -> List[ApiEndpoint]:
        """Parse all Python files in a directory"""
        all_endpoints = []
        
        for py_file in directory.rglob('*.py'):
            endpoints = self.parse_file(py_file)
            all_endpoints.extend(endpoints)
        
        return all_endpoints

def generate_html(endpoints: List[ApiEndpoint], output_file: Path, template_file: Path):
    """Generate HTML documentation using Jinja2 template"""
    
    # Group endpoints by group and collect group orders
    grouped_endpoints = {}
    group_orders = {}
    group_doc_orders = {}
    
    for endpoint in endpoints:
        group = endpoint.group
        if group not in grouped_endpoints:
            grouped_endpoints[group] = []
            group_orders[group] = endpoint.group_order
            group_doc_orders[group] = endpoint.group_doc_order
        grouped_endpoints[group].append(endpoint)
        
        # Use the lowest order value for the group (in case of multiple definitions)
        group_orders[group] = min(group_orders[group], endpoint.group_order)
        group_doc_orders[group] = min(group_doc_orders[group], endpoint.group_doc_order)
    
    # Sort groups by doc order for sidebar (0 = highest priority), then by content order, then alphabetically
    sorted_groups = sorted(grouped_endpoints.items(), key=lambda x: (group_doc_orders[x[0]], group_orders[x[0]], x[0]))
    
    # Convert back to ordered dict and sort endpoints within each group
    grouped_endpoints = {}
    for group, endpoints_list in sorted_groups:
        endpoints_list.sort(key=lambda x: (x.name, x.url))
        grouped_endpoints[group] = endpoints_list
    
    # Load template
    with open(template_file, 'r', encoding='utf-8') as f:
        template_content = f.read()
    
    # Load introduction content
    introduction_file = template_file.parent / 'introduction.html'
    introduction_content = ""
    if introduction_file.exists():
        with open(introduction_file, 'r', encoding='utf-8') as f:
            introduction_content = f.read()
    
    # Load sidebar header content
    sidebar_header_file = template_file.parent / 'sidebar-header.html'
    sidebar_header_content = "<h4>API Documentation</h4>"  # Default fallback
    if sidebar_header_file.exists():
        with open(sidebar_header_file, 'r', encoding='utf-8') as f:
            sidebar_header_content = f.read()
    
    template = Template(template_content)
    html_content = template.render(
        grouped_endpoints=grouped_endpoints,
        introduction_content=introduction_content,
        sidebar_header_content=sidebar_header_content
    )
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)

def main():
    parser = argparse.ArgumentParser(description='Generate API documentation from Python source files')
    parser.add_argument('-i', '--input', default='.',
                        help='Input directory to scan for Python files (default: current directory)')
    parser.add_argument('-o', '--output', default='api_docs.html',
                        help='Output HTML file (default: api_docs.html)')
    parser.add_argument('-t', '--template', default='template.html',
                        help='Template HTML file (default: template.html)')
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    template_path = Path(args.template)
    
    # Make template path relative to script location if not absolute
    if not template_path.is_absolute():
        template_path = Path(__file__).parent / template_path
    
    if not input_path.exists():
        print(f"Error: Input directory '{input_path}' does not exist")
        return 1
    
    if not template_path.exists():
        print(f"Error: Template file '{template_path}' does not exist")
        return 1
    
    print(f"Scanning {input_path} for @api comments...")
    
    doc_parser = ApiDocParser()
    endpoints = doc_parser.parse_directory(input_path)
    
    if not endpoints:
        print("No API endpoints found!")
        return 1
    
    print(f"Found {len(endpoints)} API endpoints")
    
    # Create output directory if needed
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    print(f"Generating HTML documentation to {output_path}...")
    generate_html(endpoints, output_path, template_path)
    
    print("Documentation generated successfully!")
    print(f"Open {output_path.resolve()} in your browser to view the docs")
    
    return 0

if __name__ == '__main__':
    exit(main())
#!/usr/bin/env python3

from changedetectionio.processors import available_processors
from changedetectionio.processors.processor_registry import get_processor_class, get_processor_form

# Test processor registration
print("=== Available Processors ===")
processors = available_processors()
for name, description in processors:
    print(f"Processor: {name} - {description}")

# Check if our WHOIS processor is registered
whois_processor_name = "whois_processor"
whois_found = any(name == whois_processor_name for name, _ in processors)

if whois_found:
    print(f"\nWHOIS Processor found! Getting processor class and form...")
    
    # Get the processor class
    processor_class = get_processor_class(whois_processor_name)
    print(f"Processor class: {processor_class}")
    print(f"Processor class name: {processor_class.__name__ if processor_class else None}")
    print(f"Processor class module: {processor_class.__module__ if processor_class else None}")
    
    # Get the processor form
    processor_form = get_processor_form(whois_processor_name)
    print(f"Processor form: {processor_form}")
    
    print("\nWHOIS Processor successfully registered")
else:
    print(f"\nWHOIS Processor not found in available processors")
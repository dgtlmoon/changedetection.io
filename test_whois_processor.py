#!/usr/bin/env python3

from changedetectionio.processors import available_processors
from changedetectionio.processors.processor_registry import get_processor_class
import urllib.parse
import sys

# First, verify our processor is available
print("=== Available Processors ===")
processors = available_processors()
for name, description in processors:
    print(f"Processor: {name} - {description}")

# Get the WHOIS processor class
whois_processor_class = get_processor_class("whois_processor")
if not whois_processor_class:
    print("ERROR: WHOIS processor not found in available processors.")
    sys.exit(1)

print(f"\nFound WHOIS processor class: {whois_processor_class}")

# Test the WHOIS processor directly
try:
    # Parse a domain from a URL
    url = "https://changedetection.io"
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc
    
    # Import whois and fetch information
    import whois
    whois_info = whois.whois(domain)
    
    print(f"\n=== WHOIS Information for {domain} ===")
    
    # Print the information
    if hasattr(whois_info, 'text'):
        print(whois_info.text)
    else:
        for key, value in whois_info.items():
            if value:
                print(f"{key}: {value}")
                
    print("\nSuccessfully retrieved WHOIS data!")
    
except Exception as e:
    print(f"Error fetching WHOIS data: {str(e)}")
    sys.exit(1)
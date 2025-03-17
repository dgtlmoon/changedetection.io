#!/usr/bin/env python3

from changedetectionio.processors import available_processors
from changedetectionio.processors import find_processors

# Test traditional processor discovery
print("=== Traditional Processor Discovery ===")
traditional_processors = find_processors()
for module, name in traditional_processors:
    print(f"Found processor: {name} in {module.__name__}")

# Test combined processor discovery (traditional + pluggy)
print("\n=== Combined Processor Discovery ===")
combined_processors = available_processors()
for name, description in combined_processors:
    print(f"Processor: {name} - {description}")
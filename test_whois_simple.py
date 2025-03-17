#!/usr/bin/env python3

import urllib.parse
import re
import whois

# Test with changedetection.io domain
url = "https://changedetection.io"

# Extract domain from URL
parsed_url = urllib.parse.urlparse(url)
domain = parsed_url.netloc

# Remove www. prefix if present
domain = re.sub(r'^www\.', '', domain)

# Fetch WHOIS information
print(f"Looking up WHOIS data for domain: {domain}")
whois_info = whois.whois(domain)

# Print key WHOIS data
print("\nKey WHOIS information:")
print(f"Domain Name: {whois_info.get('domain_name', 'Unknown')}")
print(f"Registrar: {whois_info.get('registrar', 'Unknown')}")
print(f"Creation Date: {whois_info.get('creation_date', 'Unknown')}")
print(f"Expiration Date: {whois_info.get('expiration_date', 'Unknown')}")
print(f"Updated Date: {whois_info.get('updated_date', 'Unknown')}")

# Format as text
whois_text = f"WHOIS Information for domain: {domain}\n\n"
for key, value in whois_info.items():
    if value:
        whois_text += f"{key}: {value}\n"

# Print the first 200 characters
print("\nFormatted WHOIS data (first 200 chars):")
print(whois_text[:200] + "...")

print("\nWHOIS lookup successful!")
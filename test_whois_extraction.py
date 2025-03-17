#!/usr/bin/env python3

import urllib.parse
import re
import sys

def extract_domain_from_url(url):
    """Extract domain from a URL"""
    parsed_url = urllib.parse.urlparse(url)
    domain = parsed_url.netloc
    
    # Remove www. prefix if present
    domain = re.sub(r'^www\.', '', domain)
    
    return domain

# Test domain extraction
test_urls = [
    "https://changedetection.io",
    "http://www.example.com/page",
    "https://subdomain.domain.co.uk/path?query=1",
    "ftp://ftp.example.org",
    "https://www.changedetection.io/page/subpage",
]

print("=== Domain Extraction Test ===")
for url in test_urls:
    domain = extract_domain_from_url(url)
    print(f"URL: {url} -> Domain: {domain}")

# Test WHOIS lookup for changedetection.io
try:
    import whois
    
    domain = extract_domain_from_url("https://changedetection.io")
    print(f"\n=== WHOIS lookup for {domain} ===")
    
    whois_info = whois.whois(domain)
    
    # Print key information
    print(f"Domain Name: {whois_info.get('domain_name', '')}")
    print(f"Registrar: {whois_info.get('registrar', '')}")
    print(f"Creation Date: {whois_info.get('creation_date', '')}")
    print(f"Expiration Date: {whois_info.get('expiration_date', '')}")
    
    print("\nWHOIS lookup successful!")
    
except ImportError:
    print("python-whois module not installed. Run: pip install python-whois")
    sys.exit(1)
except Exception as e:
    print(f"Error performing WHOIS lookup: {str(e)}")
    sys.exit(1)
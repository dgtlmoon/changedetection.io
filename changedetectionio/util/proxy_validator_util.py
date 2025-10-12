def proxy_validator(proxy: str):


    proxy = proxy.strip().lower()
    if not proxy:
        return False  # or "invalid"
    if proxy.startswith("http") or proxy.startswith("https") or proxy.startswith("socks5"):
        return True  # or "valid"
    return False
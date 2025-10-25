def as_monospaced_html_email(content: str, title: str) -> str:
    """
    Wraps `content` in a minimal, email-safe HTML template
    that forces monospace rendering across Gmail, Hotmail, Apple Mail, etc.

    Args:
        content: The body text (plain text or HTML-like).
        title: The title plaintext
    Returns:
        A complete HTML document string suitable for sending as an email body.
    """

    # All line feed types should be removed and then this function should only be fed <br>'s
    # Then it works with our <pre> styling without double linefeeds
    content = content.translate(str.maketrans('', '', '\r\n'))

    if title:
        import html
        title = html.escape(title)
    else:
        title = ''
    # 2. Full email-safe HTML
    html_email = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!--[if mso]>
    <style>
      body, div, pre, td {{ font-family: "Courier New", Courier, monospace !important; }}
    </style>
  <![endif]-->
  <title>{title}</title>
</head>
<body style="-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
  <pre role="article" aria-roledescription="email" lang="en"
       style="line-height:1.4;
              font-family: monospace, 'Courier New', Courier;
              white-space: pre-wrap; word-break: break-word;">{content}</pre>
</body>
</html>"""
    return html_email
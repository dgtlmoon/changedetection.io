# Important notes about templates

Template names should always end in ".html", ".htm", ".xml", ".xhtml", ".svg", even the `import`'ed templates.

Jinja2's `def select_jinja_autoescape(self, filename: str) -> bool:` will check the filename extension and enable autoescaping


"""Business-logic layer.

Route handlers never touch SQLAlchemy directly. They call into these
modules with primitive arguments; the modules own the transactions and
return plain dataclasses (or ORM objects detached from their session).

The admin-session (BYPASSRLS) boundary is also here: every function
that reads across orgs documents why it's allowed to do so.
"""

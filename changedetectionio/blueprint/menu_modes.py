"""Left-rail (action sidebar) display modes.

A leaf module on purpose: forms.py, flask_app.py and model/App.py all need these, and
model/App.py seeding its default from forms.py would drag the whole form stack (~550
modules) into the model layer.
"""
from flask_babel import lazy_gettext as _l

# The complete set of left-rail modes - flask_app.get_sidebar_mode_class() maps these
# (and only these) onto body classes, so a new mode here needs a new mapping there.
MENU_SIDEBAR_ACTIONMODES = [
    ('expandable', _l('Expand on hover')),  # Slim icon rail that expands on hover/focus
    ('pinned-expanded', _l('Always expanded')),  # Always expanded, never collapses
    ('minimal', _l('Stays minimal')),  # Always small, never expands
]
MENU_SIDEBAR_ACTIONMODES_DEFAULT = 'expandable'

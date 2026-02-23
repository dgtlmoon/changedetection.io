import re
import uuid as _uuid

from flask_babel import lazy_gettext as _l
from wtforms import (
    BooleanField,
    FieldList,
    Form,
    FormField,
    HiddenField,
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    TextAreaField,
)
from wtforms.validators import Length, NumberRange, Optional

from changedetectionio.llm.tokens import STRUCTURED_OUTPUT_INSTRUCTION

# The built-in instruction appended after the diff — shown as placeholder text.
DEFAULT_SUMMARY_PROMPT = (
    "Analyse all changes in this diff.\n\n"
    + STRUCTURED_OUTPUT_INSTRUCTION
)

# Allowed characters for a connection ID coming from the browser.
_CONN_ID_RE = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def sanitised_conn_id(raw):
    """Return raw if it looks like a safe identifier, otherwise a fresh UUID."""
    s = (raw or '').strip()
    return s if _CONN_ID_RE.match(s) else str(_uuid.uuid4())


class LLMConnectionEntryForm(Form):
    """Schema for a single LLM connection.

    Declaring every field here is what prevents arbitrary key injection:
    only these fields can ever reach the datastore from this form.
    """
    connection_id     = HiddenField()
    name              = StringField(_l('Name'),          validators=[Optional(), Length(max=100)])
    model             = StringField(_l('Model string'),  validators=[Optional(), Length(max=200)])
    api_key           = StringField(_l('API Key'),       validators=[Optional(), Length(max=500)])
    api_base          = StringField(_l('Base URL'),      validators=[Optional(), Length(max=500)])
    tokens_per_minute = IntegerField(_l('Tokens/min'),   validators=[Optional(), NumberRange(min=0, max=10_000_000)], default=0)
    is_default        = BooleanField(_l('Default'),      validators=[Optional()])


class LLMNewConnectionForm(Form):
    """Staging fields for the 'Add a connection' UI.

    These are read client-side by llm.js to build a new FieldList entry on click.
    They are never used server-side — render_kw sets the id attributes llm.js
    looks up with $('#llm-add-name') etc.
    """
    preset = SelectField(
        _l('Provider template'),
        validate_choice=False,
        # WTForms 3.x uses a dict for optgroups (has_groups() checks isinstance(choices, dict)).
        # An empty-string key renders as <optgroup label=""> which browsers treat as ungrouped.
        choices={
            '': [('', '')],
            _l('Cloud'): [
                ('openai-mini',      'OpenAI — gpt-4o-mini'),
                ('openai-4o',        'OpenAI — gpt-4o'),
                ('anthropic-haiku',  'Anthropic — claude-3-haiku'),
                ('anthropic-sonnet', 'Anthropic — claude-3-5-sonnet'),
                ('groq-8b',          'Groq — llama-3.1-8b-instant'),
                ('groq-70b',         'Groq — llama-3.3-70b-versatile'),
                ('gemini-flash',     'Google — gemini-1.5-flash'),
                ('mistral-small',    'Mistral — mistral-small'),
                ('deepseek',         'DeepSeek — deepseek-chat'),
                ('openrouter',       'OpenRouter (custom model)'),
            ],
            _l('Local'): [
                ('ollama-llama',   'Ollama — llama3.1'),
                ('ollama-mistral', 'Ollama — mistral'),
                ('lmstudio',       'LM Studio'),
            ],
            _l('Custom'): [
                ('custom', _l('Manual entry')),
            ],
        },
        render_kw={'id': 'llm-preset'},
    )
    name              = StringField(_l('Name'),
                            render_kw={'id': 'llm-add-name',  'size': 30,
                                       'autocomplete': 'off'})
    model             = StringField(_l('Model string'),
                            render_kw={'id': 'llm-add-model', 'size': 40,
                                       'placeholder': 'gpt-4o-mini', 'autocomplete': 'off'})
    api_key           = PasswordField(_l('API Key'),
                            render_kw={'id': 'llm-add-key',   'size': 40,
                                       'placeholder': 'sk-…', 'autocomplete': 'off'})
    api_base          = StringField(_l('Base URL'),
                            render_kw={'id': 'llm-add-base',  'size': 40,
                                       'placeholder': 'http://localhost:11434', 'autocomplete': 'off'})
    tokens_per_minute = IntegerField(_l('Tokens/min'), default=0,
                            render_kw={'id': 'llm-add-tpm',   'style': 'width: 8em;',
                                       'min': '0', 'step': '1000'})


class LLMSettingsForm(Form):
    """WTForms form for the LLM settings tab.

    llm_connection is a FieldList of LLMConnectionEntryForm entries.
    llm.js emits individual hidden inputs (llm_connection-N-fieldname) on submit
    instead of a JSON blob, so WTForms processes them through the declared schema.
    """
    llm_connection  = FieldList(FormField(LLMConnectionEntryForm), min_entries=0)
    new_connection  = FormField(LLMNewConnectionForm)

    llm_summary_prompt = TextAreaField(
        _l('Summary prompt'),
        validators=[Optional()],
        description=_l(
            'Override the instruction sent to the LLM after the diff. '
            'Leave blank to use the built-in default (structured JSON output).'
        ),
        render_kw={
            'rows': 8,
            'placeholder': DEFAULT_SUMMARY_PROMPT,
            'class': 'pure-input-1',
        },
    )

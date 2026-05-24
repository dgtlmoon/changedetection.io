"""
LLMSettings — validation/typing layer over the LLM config dict.

Storage shape (after migration update_31): everything lives under
    datastore.data['settings']['application']['llm'] = { ... }

Field names are stripped (enabled, debug, model, …). WTForms field names are
still llm_-prefixed (llm_enabled, llm_debug, …) and Pydantic Field aliases
bridge both sides, so callers don't repeat the rename.

The store stays a plain dict (orjson-serialized) — this model is hydrated on
read (model_validate) and dumped on write (model_dump). Pydantic instances
are never held in datastore.data.
"""
from typing import ClassVar, Tuple

from pydantic import BaseModel, ConfigDict, Field


LLM_DEFAULT_THINKING_BUDGET = 0
LLM_DEFAULT_MAX_SUMMARY_TOKENS = 3000
LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER = 5
LLM_DEFAULT_MAX_INPUT_CHARS = 100_000
LLM_DEFAULT_BUDGET_ACTION = 'skip_llm'


class LLMSettings(BaseModel):
    model_config = ConfigDict(
        populate_by_name=True,
        extra='allow',
    )

    enabled: bool = Field(default=True, alias='llm_enabled')
    debug: bool = Field(default=False, alias='llm_debug')
    override_diff_with_summary: bool = Field(default=True, alias='llm_override_diff_with_summary')
    restock_use_fallback_extract: bool = Field(default=True, alias='llm_restock_use_fallback_extract')
    thinking_budget: int = Field(default=LLM_DEFAULT_THINKING_BUDGET, alias='llm_thinking_budget')
    max_summary_tokens: int = Field(default=LLM_DEFAULT_MAX_SUMMARY_TOKENS, alias='llm_max_summary_tokens')
    budget_action: str = Field(default=LLM_DEFAULT_BUDGET_ACTION, alias='llm_budget_action')
    change_summary_default: str = Field(default='', alias='llm_change_summary_default')

    model: str = Field(default='', alias='llm_model')
    api_key: str = Field(default='', alias='llm_api_key')
    api_base: str = Field(default='', alias='llm_api_base')
    provider_kind: str = Field(default='', alias='llm_provider_kind')
    local_token_multiplier: int = Field(default=LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER, alias='llm_local_token_multiplier')
    token_budget_month: int = Field(default=0, alias='llm_token_budget_month')
    max_input_chars: int = Field(default=LLM_DEFAULT_MAX_INPUT_CHARS, alias='llm_max_input_chars')

    tokens_total_cumulative: int = 0
    tokens_this_month: int = 0
    tokens_month_key: str = ''
    cost_usd_total_cumulative: float = 0.0
    cost_usd_this_month: float = 0.0

    # Runtime-managed counters that must survive form submissions. The settings
    # POST handler strips these from form input before applying the merge.
    PROTECTED_FIELDS: ClassVar[Tuple[str, ...]] = (
        'tokens_total_cumulative',
        'tokens_this_month',
        'tokens_month_key',
        'cost_usd_total_cumulative',
        'cost_usd_this_month',
    )

"""
Validation/typing layer for the LLM config dict stored at
    datastore.data['settings']['application']['llm']

Storage stays a plain dict (orjson-serialized). This model is hydrated on read
(model_validate) and dumped on write (model_dump). Form-side WTForms field names
keep the llm_-prefix; Field aliases bridge them to the stripped storage names.
"""
from typing import ClassVar, Tuple

from pydantic import BaseModel, ConfigDict, Field


LLM_DEFAULT_THINKING_BUDGET = 0
LLM_DEFAULT_MAX_SUMMARY_TOKENS = 3000
LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER = 5
LLM_DEFAULT_MAX_INPUT_CHARS = 100_000
LLM_DEFAULT_BUDGET_ACTION = 'skip_llm'


class LLMSettings(BaseModel):
    # extra='forbid' rejects any key that isn't a declared field/alias with a
    # ValidationError. Loud failure forces new form fields to be declared here
    # before they can land in storage — closes the CWE-915 mass-assignment class
    # of bugs (see GHSA-h3x5-5j56-hm2j for the canonical example).
    model_config = ConfigDict(populate_by_name=True, extra='forbid')

    enabled: bool = Field(default=True, alias='llm_enabled')
    debug: bool = Field(default=False, alias='llm_debug')
    override_diff_with_summary: bool = Field(default=True, alias='llm_override_diff_with_summary')
    restock_use_fallback_extract: bool = Field(default=True, alias='llm_restock_use_fallback_extract')
    thinking_budget: int = Field(default=LLM_DEFAULT_THINKING_BUDGET, alias='llm_thinking_budget')
    max_summary_tokens: int = Field(default=LLM_DEFAULT_MAX_SUMMARY_TOKENS, alias='llm_max_summary_tokens')
    budget_action: str = Field(default=LLM_DEFAULT_BUDGET_ACTION, alias='llm_budget_action')
    change_summary_default: str = Field(default='', alias='llm_change_summary_default')
    token_budget_month: int = Field(default=0, alias='llm_token_budget_month')
    max_input_chars: int = Field(default=LLM_DEFAULT_MAX_INPUT_CHARS, alias='llm_max_input_chars')
    # Per-call and per-watch token caps; read by _check_token_budget() in evaluator.py.
    # 0 means unlimited.
    max_tokens_per_check: int = Field(default=0, alias='llm_max_tokens_per_check')
    max_tokens_cumulative: int = Field(default=0, alias='llm_max_tokens_cumulative')

    model: str = Field(default='', alias='llm_model')
    api_key: str = Field(default='', alias='llm_api_key')
    api_base: str = Field(default='', alias='llm_api_base')
    provider_kind: str = Field(default='', alias='llm_provider_kind')
    local_token_multiplier: int = Field(default=LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER, alias='llm_local_token_multiplier')

    tokens_total_cumulative: int = 0
    tokens_this_month: int = 0
    tokens_month_key: str = ''
    cost_usd_total_cumulative: float = 0.0
    cost_usd_this_month: float = 0.0

    # Provider-connection fields wiped on /llm/clear and when the model is emptied.
    CONNECTION_FIELDS: ClassVar[Tuple[str, ...]] = (
        'model', 'api_key', 'api_base', 'provider_kind', 'local_token_multiplier',
    )
    # Runtime-managed counters — form submissions must never overwrite these.
    PROTECTED_FIELDS: ClassVar[Tuple[str, ...]] = (
        'tokens_total_cumulative', 'tokens_this_month', 'tokens_month_key',
        'cost_usd_total_cumulative', 'cost_usd_this_month',
    )

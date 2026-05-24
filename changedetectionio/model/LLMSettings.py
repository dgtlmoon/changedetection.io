"""
Validation/typing layer for the LLM config dict stored at
    datastore.data['settings']['application']['llm']

Storage stays a plain dict (orjson-serialized). This model is hydrated on read
(model_validate) and dumped on write (model_dump). WTForms field names match
the storage field names exactly — no aliases needed.
"""
from typing import ClassVar, Tuple

from pydantic import BaseModel, ConfigDict


LLM_DEFAULT_THINKING_BUDGET = 0
LLM_DEFAULT_MAX_SUMMARY_TOKENS = 3000
LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER = 5
LLM_DEFAULT_MAX_INPUT_CHARS = 100_000
LLM_DEFAULT_BUDGET_ACTION = 'skip_llm'


class LLMSettings(BaseModel):
    # extra='forbid' rejects any key that isn't a declared field with a
    # ValidationError. Loud failure forces new form fields to be declared here
    # before they can land in storage — closes the CWE-915 mass-assignment class
    # of bugs (see GHSA-h3x5-5j56-hm2j for the canonical example).
    model_config = ConfigDict(extra='forbid')

    enabled: bool = True
    debug: bool = False
    override_diff_with_summary: bool = True
    restock_use_fallback_extract: bool = True
    thinking_budget: int = LLM_DEFAULT_THINKING_BUDGET
    max_summary_tokens: int = LLM_DEFAULT_MAX_SUMMARY_TOKENS
    budget_action: str = LLM_DEFAULT_BUDGET_ACTION
    change_summary_default: str = ''
    token_budget_month: int = 0
    max_input_chars: int = LLM_DEFAULT_MAX_INPUT_CHARS
    # Per-watch per-period token cap; read by _check_token_budget() in evaluator.py.
    # 0 means unlimited. Once a watch's usage within the current period hits this cap,
    # AI evaluation is skipped for it until the period rolls over. Period is currently
    # hard-coded to month (matches the global counter rollover); name is period-agnostic
    # to leave room for a configurable period (day/week/month) later.
    max_tokens_per_count_period: int = 0

    model: str = ''
    api_key: str = ''
    api_base: str = ''
    provider_kind: str = ''
    local_token_multiplier: int = LLM_DEFAULT_LOCAL_TOKEN_MULTIPLIER

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

"""Sprint 8.3.6 prompt templates (system + user + response_schema)."""

from imga_api.llm.prompts.okr_v1 import (
    OKR_RESPONSE_SCHEMA,
    OKR_SYSTEM_PROMPT,
    OKR_USER_PROMPT_TEMPLATE,
    render_okr_user_prompt,
)
from imga_api.llm.prompts.swot_v1 import (
    SWOT_RESPONSE_SCHEMA,
    SWOT_SYSTEM_PROMPT,
    SWOT_USER_PROMPT_TEMPLATE,
    render_swot_user_prompt,
)

__all__ = [
    "OKR_RESPONSE_SCHEMA",
    "OKR_SYSTEM_PROMPT",
    "OKR_USER_PROMPT_TEMPLATE",
    "SWOT_RESPONSE_SCHEMA",
    "SWOT_SYSTEM_PROMPT",
    "SWOT_USER_PROMPT_TEMPLATE",
    "render_okr_user_prompt",
    "render_swot_user_prompt",
]

"""Sprint 8.3.6 — api-side LLM glue.

The provider + rotator + error hierarchy live in ``imga_core.llm``;
this package layer hosts:

  * ``prompts/swot_v1`` — system + user templates + response_schema for
    SWOT generation.
  * (Sprint 8.3.6.4) ``prompts/okr_v1`` — same shape for OKR.

Templates are kept under api/llm/prompts because they're sent to the
LLM by the api service layer (SWOT/OKR generators). imga-core's prompt
file is for the classification fallback path and stays separate to
avoid mixing concerns.
"""

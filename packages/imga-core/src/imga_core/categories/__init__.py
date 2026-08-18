"""Category taxonomy + per-category Turkish keyword lexicons."""

from imga_core.categories.taxonomy import (
    DEFAULT_GLOBAL_CATEGORIES,
    FALLBACK_CATEGORY_CODE,
    GLOBAL_CATEGORY_BY_CODE,
    GLOBAL_CATEGORY_CODES,
    CategoryDefinition,
    GlobalCategory,
    ensure_fallback_category,
)

__all__ = [
    "DEFAULT_GLOBAL_CATEGORIES",
    "FALLBACK_CATEGORY_CODE",
    "GLOBAL_CATEGORY_BY_CODE",
    "GLOBAL_CATEGORY_CODES",
    "CategoryDefinition",
    "GlobalCategory",
    "ensure_fallback_category",
]

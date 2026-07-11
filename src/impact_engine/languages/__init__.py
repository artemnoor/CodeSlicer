"""Language Registry module."""
from impact_engine.languages.models import LanguageProfile
from impact_engine.languages.registry import (
    list_language_profiles,
    get_language_profile,
    detect_languages
)

__all__ = [
    "LanguageProfile",
    "list_language_profiles",
    "get_language_profile",
    "detect_languages"
]

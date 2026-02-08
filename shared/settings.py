"""
User Settings Manager Module
======================

Provides user settings interface where users can customize:
- Language preference
- Default LLM selection
- System prompt configuration
- Other personal preferences
"""

from typing import Dict, Any, Optional, Tuple
from core.logging import log
from shared.users import get_user_manager, UserRole

class UserSettingsManager:
    """Manages user settings and preferences."""

    def __init__(self):
        self.user_manager = get_user_manager()

    def get_user_settings(self, user_id: str) -> Dict[str, Any]:
        """Get all settings for a user."""
        user = self.user_manager.get_user(user_id)
        if not user:
            return {}

        # Get base settings from user profile
        settings = user.get("profile", {}).get("settings", {})

        # Ensure default structure
        default_settings = {
            "language": "en",
            "default_llm": None,
            "system_prompt": "",
            "temperature": 0.7,
            "max_tokens": 1000,
            "auto_save": True,
            "notifications": True,
            "theme": "light"
        }

        # Merge with defaults
        for key, value in default_settings.items():
            if key not in settings:
                settings[key] = value

        return settings

    def update_user_settings(self, user_id: str, settings_updates: Dict[str, Any]) -> bool:
        """Update user settings."""
        user = self.user_manager.get_user(user_id)
        if not user:
            return False

        # Get current profile
        profile = user.get("profile", {})

        # Get current settings or create new
        current_settings = profile.get("settings", {})

        # Update settings
        current_settings.update(settings_updates)

        # Update user profile
        profile["settings"] = current_settings

        # Save to database
        return self.user_manager.update_user(
            user_id,
            current_user_id=user_id,
            profile=profile
        )

    def get_language_options(self) -> list:
        """Get available language options."""
        # In a real implementation, this would come from config or translation system
        return [
            {"code": "en", "name": "English", "flag": "🇺🇸"},
            {"code": "fr", "name": "Français", "flag": "🇫🇷"},
            {"code": "de", "name": "Deutsch", "flag": "🇩🇪"},
            {"code": "es", "name": "Español", "flag": "🇪🇸"},
            {"code": "it", "name": "Italiano", "flag": "🇮🇹"},
            {"code": "zh", "name": "中文", "flag": "🇨🇳"},
            {"code": "ja", "name": "日本語", "flag": "🇯🇵"},
            {"code": "ko", "name": "한국어", "flag": "🇰🇷"},
        ]

    def get_user_preferences(self, user: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """
        Get user's preferred language and LLM from their profile settings.

        Args:
            user: User dictionary from user manager

        Returns:
            Tuple of (preferred_language, preferred_llm_id) or (None, None) if not found
        """
        if not user:
            return None, None

        # Check if user has profile settings
        profile = user.get("profile", {})
        preferred_lang = None
        preferred_llm = None

        # Check new settings structure
        if "settings" in profile:
            settings = profile.get("settings", {})

            # Get language preference
            if "language" in settings:
                preferred_lang = settings.get("language")
            else:
                # Fall back to old profile language field
                if "language" in profile:
                    preferred_lang = profile.get("language")

            # Get LLM preference
            if "default_llm" in settings:
                preferred_llm = settings.get("default_llm")

        else:
            # Old structure: language might be directly in profile
            if "language" in profile:
                preferred_lang = profile.get("language")

        return preferred_lang, preferred_llm

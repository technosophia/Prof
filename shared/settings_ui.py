"""
User Settings UI Module
======================

Provides user settings interface where users can customize:
- Language preference
- Default LLM selection
- System prompt configuration
- Other personal preferences
"""

import streamlit as st
from typing import Dict, Any, Optional, Tuple
from shared.common import _, log, get_config, get_user_settings_manager
from shared.common import get_available_llms, set_current_llm, get_current_llm_info
from shared.common import get_available_languages
from shared.common import UserRole

def get_llm_options() -> list:
    """Get available LLM options for dropdown."""
    available_llms = get_available_llms()
    options = []

    for llm in available_llms:
        if llm.get("available", False):
            status = "🟢" if llm.get("enabled", False) else "🟡"
            display_name = f"{status} {llm.get('name', 'Unknown')} ({llm.get('type', 'Unknown')})"
            options.append({
                "id": llm.get("id"),
                "name": llm.get("name"),
                "display": display_name,
                "type": llm.get("type"),
                "model": llm.get("model")
            })

    return options

def show_settings_content():
    """Display the settings page content."""
    current_user = st.session_state.get("current_user")

    if not current_user:
        st.error("Please log in to access settings.")
        return

    user_id = current_user.get("id")
    user_name = current_user.get("name")
    user_role = current_user.get("role")

    st.header(f"⚙️ Settings for {user_name}")

    # Role badge
    role_emoji = "👑" if user_role == UserRole.ADMIN.value else "⭐" if user_role == UserRole.MASTER.value else "👤"
    st.caption(f"{role_emoji} {user_role.capitalize()} User")

    # Initialize settings manager
    settings_manager = get_user_settings_manager()

    # Get current settings
    current_settings = settings_manager.get_user_settings(user_id)

    # Create tabs for different settings categories
    tab1, tab2, tab3, tab4 = st.tabs(["🌍 Language & LLM", "🤖 System Prompt", "⚡ Preferences", "📊 Info"])

    with tab1:
        st.subheader("Language & LLM Settings")

        # Language selection
        st.write("#### Language Preference")
        language_options = settings_manager.get_language_options()

        # Find current language
        current_language = current_settings.get("language", "en")
        default_lang_idx = 0
        for idx, lang in enumerate(language_options):
            if lang["code"] == current_language:
                default_lang_idx = idx
                break

        selected_language = st.selectbox(
            "Select your preferred language",
            options=[lang["code"] for lang in language_options],
            format_func=lambda x: f"{[lang['flag'] for lang in language_options if lang['code'] == x][0]} {[lang['name'] for lang in language_options if lang['code'] == x][0]}",
            index=default_lang_idx,
            key="settings_language_select"
        )

        st.caption("This will affect the language of the interface and responses.")

        # LLM selection
        st.divider()
        st.write("#### Default LLM Selection")

        llm_options = get_llm_options()

        if not llm_options:
            st.warning("No LLMs available. Please configure LLMs in the admin panel.")
        else:
            # Get current LLM from settings or use global default
            current_llm_id = current_settings.get("default_llm")

            # Find current LLM index
            default_llm_idx = 0
            if current_llm_id:
                for idx, llm in enumerate(llm_options):
                    if llm["id"] == current_llm_id:
                        default_llm_idx = idx
                        break

            selected_llm_id = st.selectbox(
                "Choose your preferred LLM",
                options=[llm["id"] for llm in llm_options],
                format_func=lambda x: [llm["display"] for llm in llm_options if llm["id"] == x][0],
                index=default_llm_idx,
                key="settings_llm_select"
            )

            # Show LLM info
            if selected_llm_id:
                selected_llm = next((llm for llm in llm_options if llm["id"] == selected_llm_id), None)
                if selected_llm:
                    with st.expander("Selected LLM Details"):
                        st.write(f"**Name:** {selected_llm['name']}")
                        st.write(f"**Type:** {selected_llm['type']}")
                        st.write(f"**Model:** {selected_llm.get('model', 'N/A')}")
                        st.write(f"**Status:** Available ✅")

    with tab2:
        st.subheader("System Prompt Configuration")

        st.write("#### Custom System Prompt")
        st.caption("This prompt will be used to guide the AI's behavior and responses.")

        # Get current system prompt
        current_prompt = current_settings.get("system_prompt", "")

        # Text area for system prompt
        system_prompt = st.text_area(
            "Enter your custom system prompt",
            value=current_prompt,
            height=200,
            placeholder="You are a helpful AI assistant. You provide clear, concise, and accurate information. You respond in the user's preferred language when possible.",
            key="settings_system_prompt"
        )

        # Prompt examples
        with st.expander("💡 Prompt Examples"):
            st.write("**General Assistant:**")
            st.code("You are a helpful, respectful, and honest assistant. Always answer as helpfully as possible, while being safe.")

            st.write("**Language Teacher:**")
            st.code("You are a language learning assistant. You help users learn languages through conversation, explanations, and exercises.")

            st.write("**Technical Expert:**")
            st.code("You are a technical expert. You provide detailed, accurate technical explanations with code examples when appropriate.")

        # Prompt length counter
        prompt_length = len(system_prompt)
        st.caption(f"Prompt length: {prompt_length} characters")

        if prompt_length > 2000:
            st.warning("⚠️ Long prompts may affect performance and token usage.")

    with tab3:
        st.subheader("General Preferences")

        col1, col2 = st.columns(2)

        with col1:
            # Temperature setting
            temperature = st.slider(
                "Temperature",
                min_value=0.0,
                max_value=2.0,
                value=float(current_settings.get("temperature", 0.7)),
                step=0.1,
                help="Higher values make output more random, lower values more deterministic."
            )

            # Max tokens
            max_tokens = st.number_input(
                "Max Tokens per Response",
                min_value=100,
                max_value=4000,
                value=int(current_settings.get("max_tokens", 1000)),
                step=100,
                help="Maximum length of AI responses."
            )

        with col2:
            # Auto-save
            auto_save = st.toggle(
                "Auto-save Conversations",
                value=current_settings.get("auto_save", True),
                help="Automatically save conversation history."
            )

            # Notifications
            notifications = st.toggle(
                "Enable Notifications",
                value=current_settings.get("notifications", True),
                help="Show notification messages."
            )

        # Theme selection
        theme_options = ["light", "dark", "auto"]
        current_theme = current_settings.get("theme", "light")
        theme_idx = theme_options.index(current_theme) if current_theme in theme_options else 0

        theme = st.selectbox(
            "Interface Theme",
            options=theme_options,
            index=theme_idx,
            format_func=lambda x: x.title(),
            help="Choose your preferred color theme."
        )

    with tab4:
        st.subheader("User Information")

        col1, col2 = st.columns(2)

        with col1:
            st.write("**Account Details**")
            st.write(f"**Username:** {user_name}")
            st.write(f"**User ID:** {user_id}")
            st.write(f"**Role:** {user_role.capitalize()}")

            if current_user.get("email"):
                st.write(f"**Email:** {current_user.get('email')}")

            if current_user.get("parent_name"):
                st.write(f"**Managed by:** {current_user.get('parent_name')}")

        with col2:
            st.write("**Usage Statistics**")
            # Placeholder for future stats
            st.write("**Conversations:** 0")
            st.write("**Messages:** 0")
            st.write("**Tokens Used:** 0")

            # Account creation date
            if current_user.get("created_at"):
                st.write(f"**Member since:** {current_user.get('created_at')[:10]}")

        st.divider()
        st.write("**Current Settings Summary**")

        # Display current settings as JSON
        with st.expander("View Raw Settings"):
            st.json(current_settings)

        # Reset to defaults button
        if st.button("🔄 Reset to Defaults", type="secondary"):
            st.warning("This will reset all your settings to default values.")
            col_reset1, col_reset2 = st.columns(2)
            with col_reset1:
                if st.button("✅ Confirm Reset"):
                    default_reset = {
                        "language": "en",
                        "default_llm": None,
                        "system_prompt": "",
                        "temperature": 0.7,
                        "max_tokens": 1000,
                        "auto_save": True,
                        "notifications": True,
                        "theme": "light"
                    }
                    success = settings_manager.update_user_settings(user_id, default_reset)
                    if success:
                        st.success("Settings reset to defaults!")
                        st.rerun()
                    else:
                        st.error("Failed to reset settings.")
            with col_reset2:
                if st.button("❌ Cancel"):
                    st.rerun()

    # Save button at the bottom
    st.divider()

    col_save1, col_save2, col_save3 = st.columns([1, 1, 2])

    with col_save1:
        if st.button("💾 Save Settings", type="primary", width='stretch'):
            # Collect all settings
            settings_updates = {
                "language": selected_language,
                "default_llm": selected_llm_id if 'selected_llm_id' in locals() else current_settings.get("default_llm"),
                "system_prompt": system_prompt if 'system_prompt' in locals() else current_settings.get("system_prompt", ""),
                "temperature": temperature if 'temperature' in locals() else current_settings.get("temperature", 0.7),
                "max_tokens": max_tokens if 'max_tokens' in locals() else current_settings.get("max_tokens", 1000),
                "auto_save": auto_save if 'auto_save' in locals() else current_settings.get("auto_save", True),
                "notifications": notifications if 'notifications' in locals() else current_settings.get("notifications", True),
                "theme": theme if 'theme' in locals() else current_settings.get("theme", "light")
            }

            # Update settings
            success = settings_manager.update_user_settings(user_id, settings_updates)

            if success:
                st.success("✅ Settings saved successfully!")

                # Update session state if language changed
                if selected_language != st.session_state.current_language:
                    st.session_state.current_language = selected_language

                # Update current user in session state
                updated_user = get_user_manager().get_user(user_id)
                if updated_user:
                    st.session_state.current_user = updated_user

                log("info", f"User settings updated for {user_name}")
                st.rerun()
            else:
                st.error("❌ Failed to save settings. Please try again.")

    with col_save2:
        if st.button("❌ Cancel", width='stretch'):
            st.rerun()

    with col_save3:
        st.caption("Settings are saved per user and persist across sessions.")

def inject_ui_settings_content():
    """Inject settings content."""
    st.write("Settings Content")
    return show_settings_content()

def inject_ui_sidebar():
    """Add language and LLM selectors to sidebar that reflect user preferences."""

    # Get current user
    current_user = st.session_state.get("current_user")
    if not current_user:
        return None

    # Get settings manager
    settings_manager = get_user_settings_manager()

    # Get user preferences
    preferred_lang, preferred_llm = settings_manager.get_user_preferences(current_user)

    # Show available languages
    available_langs = get_available_languages()

    # Better mapping for display names
    lang_names = {
        "en": "English",
        "fr": "Français",
        # Add more here later
    }

    # Compute default index based on user preference or current session
    current_lang = preferred_lang if preferred_lang else st.session_state.current_language

    try:
        default_index = available_langs.index(current_lang)
    except ValueError:
        default_index = 0  # fallback to first

    # Language selector - in a container to control layout
    with st.container():
        col1, col2 = st.columns([2, 3])

        # Language selector
        lang_option = col1.selectbox(
            "🌍 " + _("language_select"),
            options=available_langs,
            format_func=lambda x: lang_names.get(x, x.upper()),
            index=default_index,
            key="language_selector"
        )

        # Handle language change
        if lang_option != st.session_state.current_language:
            old_lang = st.session_state.current_language
            st.session_state.current_language = lang_option

            log("info", f"Language changed from '{old_lang}' to '{lang_option}' (via sidebar)")
            st.rerun()

    # Get available LLMs
    available_llms_list = get_available_llms()

    # Get current LLM info
    current_llm_info = get_current_llm_info()

    # Create list of available LLMs for dropdown
    llm_options = []
    llm_display_names = []

    for llm_item in available_llms_list:
        if llm_item["available"]:
            status_icon = "🟢" if llm_item["enabled"] else "🔴"
            display_name = f"{status_icon} {llm_item['name']} ({llm_item['type']})"
            llm_options.append(llm_item["id"])
            llm_display_names.append(display_name)

    # LLM selector
    if llm_options:
        # Find current LLM index
        current_index = 0
        current_llm_id = current_llm_info.get("id") if current_llm_info else None

        # Use user's preferred LLM as default if available
        if preferred_llm and preferred_llm in llm_options:
            try:
                current_index = llm_options.index(preferred_llm)
            except ValueError:
                pass
        elif current_llm_id and current_llm_id in llm_options:
            try:
                current_index = llm_options.index(current_llm_id)
            except ValueError:
                pass

        selected_llm_id = col2.selectbox(
            "🤖 " + _("select_llm"),
            options=llm_options,
            format_func=lambda x: llm_display_names[llm_options.index(x)],
            index=current_index,
            key="llm_selector"
        )

        # Check if LLM changed
        if selected_llm_id != (current_llm_info.get("id") if current_llm_info else None):
            if set_current_llm(selected_llm_id):
                log("info", f"LLM changed to: {selected_llm_id} (via sidebar)")
                st.rerun()
            else:
                st.error(f"Failed to switch to LLM: {selected_llm_id}")

    # Show current preferences info
    if preferred_lang:
        lang_display = lang_names.get(preferred_lang, preferred_lang.upper())
        st.caption(f"👤 User pref: 🌍 {lang_display}")

    if preferred_llm and current_llm_info:
        # Find the LLM name
        llm_name = current_llm_info.get("name", "Unknown")
        st.caption(f"👤 User pref: 🤖 {llm_name}")

    return None

def inject_ui_initialize():
    """Initialize settings module."""
    if "user_settings_manager" not in st.session_state:
        st.session_state.user_settings_manager = get_user_settings_manager()

    log("debug", "Settings UI module initialized")

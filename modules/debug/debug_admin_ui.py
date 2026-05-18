"""
Debug Admin UI Module
====================

Provides a simple debug/testing interface in the admin panel with tabs for:
1. Text and LLM Testing
2. Configuration Inspection
3. UI Registry Inspection
4. Quick Tests

This module adds a "Debug" tab to the admin interface.
"""

import streamlit as st
import asyncio
import json
from typing import Optional

from st_shared.cached import get_config, get_user_manager
from shared.common import llm_conversation_generate, get_current_llm_info
from modules.debug.debug_profiler_tab import show_profiler_tab


# Try to import ui_registry for injection point debugging
from core.logging import log, set_log_module_level
from st_shared.cached import _
try:
    from shared.ui_registry import UIRegistry
    UI_REGISTRY_AVAILABLE = True
except ImportError:
    UI_REGISTRY_AVAILABLE = False
    log("warning", "UI registry not available for import")


def show_text_llm_tab():
    """Tab 1: Text Input and LLM Testing."""
    st.header("📝 Text & LLM Testing")

    # Section 1: Text Input Test
    st.subheader("📝 Text Input Test")

    # Initialize session state for debug text
    if 'debug_test_text' not in st.session_state:
        st.session_state.debug_test_text = ""

    if 'debug_test_result' not in st.session_state:
        st.session_state.debug_test_result = ""

    if 'debug_llm_response' not in st.session_state:
        st.session_state.debug_llm_response = ""

    if 'debug_llm_loading' not in st.session_state:
        st.session_state.debug_llm_loading = False

    # Text input
    test_text = st.text_area(
        "Enter some text for testing:",
        value=st.session_state.debug_test_text,
        height=100,
        key="debug_text_input",
        help="Enter any text you want to test with"
    )

    # Update session state
    st.session_state.debug_test_text = test_text

    col1, col2 = st.columns(2)

    with col1:
        # Button to display text
        if st.button("📤 Display Text", width='stretch'):
            if test_text.strip():
                st.session_state.debug_test_result = test_text
                st.success("Text captured! Check the result section below.")
                log("debug", f"Debug text captured: {test_text[:50]}...")
            else:
                st.warning("Please enter some text first")

    with col2:
        # Button to clear text
        if st.button("🗑️ Clear Text", width='stretch', type="secondary"):
            st.session_state.debug_test_text = ""
            st.session_state.debug_test_result = ""
            st.session_state.debug_llm_response = ""
            st.rerun()

    # Display result section
    if st.session_state.debug_test_result:
        st.divider()
        st.subheader("📋 Text Result")
        st.info(st.session_state.debug_test_result)

        # Additional info
        st.caption(f"Character count: {len(st.session_state.debug_test_result)}")
        st.caption(f"Word count: {len(st.session_state.debug_test_result.split())}")

    st.divider()

    # Section 2: LLM Test
    st.subheader("🤖 LLM Test")

    # Get current LLM info
    current_llm_info = get_current_llm_info()

    if current_llm_info:
        st.write(f"**Current LLM:** {current_llm_info.get('name', 'Unknown')}")
        st.write(f"**Type:** {current_llm_info.get('type', 'Unknown')}")
        st.write(f"**Model:** {current_llm_info.get('model', 'Unknown')}")
        st.write(f"**Status:** {'🟢 Available' if current_llm_info.get('available') else '🔴 Unavailable'}")

        # LLM question input
        llm_question = st.text_input(
            "Question for LLM:",
            value="What is 2+2?",
            key="debug_llm_question",
            help="Enter a question to ask the current LLM"
        )

        col3, col4 = st.columns(2)

        with col3:
            # Button to ask LLM
            if st.button("💭 Ask LLM", width='stretch', type="primary"):
                if llm_question.strip():
                    st.session_state.debug_llm_loading = True
                    st.rerun()
                else:
                    st.warning("Please enter a question")

        with col4:
            # Button to clear LLM response
            if st.button("🗑️ Clear Response", width='stretch', type="secondary"):
                st.session_state.debug_llm_response = ""
                st.rerun()

        # Handle LLM query
        if st.session_state.debug_llm_loading:
            try:
                # Create a placeholder for streaming
                response_placeholder = st.empty()
                stream_buffer = ""

                # Define streaming callback
                def stream_callback(chunk):
                    nonlocal stream_buffer
                    stream_buffer += chunk
                    response_placeholder.markdown(stream_buffer)

                # Call the LLM
                with st.spinner(f"Asking {current_llm_info.get('name')}..."):
                    response = asyncio.run(
                        llm_conversation_generate(
                            llm_question.strip(),
                            stream_callback
                        )
                    )

                st.session_state.debug_llm_response = response
                st.session_state.debug_llm_loading = False
                log("info", f"Debug LLM query completed: {llm_question[:50]}...")
                st.rerun()

            except Exception as e:
                error_msg = f"Error calling LLM: {str(e)}"
                st.error(error_msg)
                log("error", error_msg, stacktrace=True)
                st.session_state.debug_llm_loading = False
                st.session_state.debug_llm_response = f"Error: {str(e)}"
                st.rerun()

        # Display LLM response
        if st.session_state.debug_llm_response:
            st.divider()
            st.subheader("🤖 LLM Response")

            # Check if it's an error message
            if st.session_state.debug_llm_response.startswith("Error:"):
                st.error(st.session_state.debug_llm_response)
            else:
                st.info(st.session_state.debug_llm_response)

            # Response info
            st.caption(f"Response length: {len(st.session_state.debug_llm_response)} characters")

            # Copy button
            if st.button("📋 Copy Response", key="copy_debug_response"):
                st.write("Response copied to clipboard! (In a real app, you'd use clipboard API)")
    else:
        st.warning("No LLM available. Please configure an LLM in the settings.")


def show_config_tab():
    """Tab 2: Configuration Inspection with Logging Control."""
    st.header("⚙️ Configuration Inspection & Logging Control")

    # SECTION 1: Logging System Control
    st.subheader("🔊 Logging System Control")

    # Get current logging state
    from core.logging import (
        set_logging_disengaged, is_logging_disengaged,
        set_level, get_log_level, get_all_module_levels, reset_module_level,
        debug, info, warning, error
    )

    current_disengaged = is_logging_disengaged()
    current_global_level = get_log_level()

    # IMPORTANT: Use session state to track if we're in the middle of an update
    # This prevents infinite loops from reruns triggering more logs
    if 'logging_update_in_progress' not in st.session_state:
        st.session_state.logging_update_in_progress = False

    if 'previous_log_level' not in st.session_state:
        st.session_state.previous_log_level = current_global_level

    # Create tabs for different logging controls
    log_tab1, log_tab2, log_tab3 = st.tabs(["🎮 Main Control", "📦 Module Levels", "🧪 Test"])

    with log_tab1:
        # Main control section
        col_status, col_toggle, col_level = st.columns([2, 1, 1])

        with col_status:
            # Status display
            if current_disengaged:
                st.error("🔴 **Logging is DISENGAGED** - All log calls are no-ops")
                st.caption("Performance is maximized but no logs will be written")
            else:
                st.success("🟢 **Logging is ENGAGED** - Normal logging operation")
                st.caption(f"Global level: **{current_global_level}**")

        with col_toggle:
            # Toggle disengage button
            if current_disengaged:
                if st.button("🔊 Re-engage Logging", type="primary", use_container_width=True):
                    # Set flag to prevent logging during update
                    st.session_state.logging_update_in_progress = True
                    set_logging_disengaged(False)
                    st.rerun()
            else:
                if st.button("🔇 Disengage Logging", type="secondary", use_container_width=True):
                    st.session_state.logging_update_in_progress = True
                    set_logging_disengaged(True)
                    st.rerun()

        with col_level:
            # Global level control (only if not disengaged)
            if not current_disengaged:
                # Use a unique key for the selectbox that doesn't change on rerun
                level_options = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

                # Create a selectbox with a stable key
                selected_level = st.selectbox(
                    "Global Level",
                    options=level_options,
                    index=level_options.index(current_global_level) if current_global_level in level_options else 1,
                    key="global_log_level_selectbox",  # Stable key
                    label_visibility="collapsed"
                )

                # Only trigger update if:
                # 1. The selected level is different from current
                # 2. We're not already in an update
                # 3. The selectbox was actually interacted with (using session state to track)
                if 'last_selected_level' not in st.session_state:
                    st.session_state.last_selected_level = selected_level

                if (selected_level != current_global_level and
                    not st.session_state.logging_update_in_progress and
                    selected_level != st.session_state.last_selected_level):

                    # Update tracking
                    st.session_state.last_selected_level = selected_level
                    st.session_state.logging_update_in_progress = True

                    # Set the new level WITHOUT using rerun
                    # Instead, update directly and rely on Streamlit's natural refresh
                    set_level(selected_level)

                    # Clear the flag after a short delay (handled by session state)
                    # We'll clear it on next render
                elif st.session_state.logging_update_in_progress:
                    # Clear the flag now that we've rendered
                    st.session_state.logging_update_in_progress = False

        # Show current global level info
        if not current_disengaged:
            st.info(f"📢 **Current global log level: {current_global_level}**")

            # Level descriptions
            with st.expander("📖 Log Level Descriptions", expanded=False):
                st.markdown("""
                - **DEBUG**: Detailed information, typically of interest only when diagnosing problems
                - **INFO**: Confirmation that things are working as expected
                - **WARNING**: Indication that something unexpected happened, but the application is still working
                - **ERROR**: Due to a more serious problem, the application couldn't perform some function
                - **CRITICAL**: A serious error, indicating that the application itself may be unable to continue running
                """)

    with log_tab2:
        # Module-specific level control
        st.markdown("##### 📦 Module-Specific Log Levels")
        st.caption("Set different log levels for specific modules (overrides global level)")

        # Get all module levels
        module_levels = get_all_module_levels()

        # Input for new module level
        col_mod1, col_mod2, col_mod3 = st.columns([2, 1, 1])

        with col_mod1:
            new_module = st.text_input(
                "Module name",
                placeholder="e.g., core.auth, modules.debug",
                key="new_module_name_input"
            )

        with col_mod2:
            new_module_level = st.selectbox(
                "Level",
                options=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
                index=1,
                key="new_module_level_select"
            )

        with col_mod3:
            st.write("")  # Spacing
            st.write("")  # Spacing
            if st.button("➕ Add/Update", use_container_width=True, key="add_module_level_btn"):
                if new_module:
                    st.session_state.logging_update_in_progress = True
                    set_level(new_module_level, new_module)
                    st.rerun()
                else:
                    st.warning("Please enter a module name")

        # Display current module levels
        if module_levels:
            st.markdown("##### Current Module Levels")

            # Display as table with reset buttons
            for module, level in sorted(module_levels.items()):
                col_mod_disp, col_level_disp, col_reset = st.columns([3, 1, 1])
                with col_mod_disp:
                    st.code(module, language="")
                with col_level_disp:
                    # Color-code the level
                    level_color = {
                        "DEBUG": "🟣",
                        "INFO": "🔵",
                        "WARNING": "🟡",
                        "ERROR": "🟠",
                        "CRITICAL": "🔴"
                    }.get(level, "⚪")
                    st.markdown(f"{level_color} **{level}**")
                with col_reset:
                    if st.button("Reset", key=f"reset_module_{module}", use_container_width=True):
                        st.session_state.logging_update_in_progress = True
                        reset_module_level(module)
                        st.rerun()
        else:
            st.info("No module-specific levels set. All modules use the global level.")

        # Quick preset buttons for common modules
        st.markdown("##### ⚡ Quick Presets")
        col_preset1, col_preset2, col_preset3, col_preset4 = st.columns(4)

        with col_preset1:
            if st.button("🐍 All DEBUG", use_container_width=True, key="preset_all_debug"):
                st.session_state.logging_update_in_progress = True
                set_level("DEBUG")  # Global
                st.rerun()

        with col_preset2:
            if st.button("ℹ️ All INFO", use_container_width=True, key="preset_all_info"):
                st.session_state.logging_update_in_progress = True
                set_level("INFO")  # Global
                st.rerun()

        with col_preset3:
            if st.button("⚠️ All WARNING", use_container_width=True, key="preset_all_warning"):
                st.session_state.logging_update_in_progress = True
                set_level("WARNING")  # Global
                st.rerun()

        with col_preset4:
            if st.button("🔄 Reset All", use_container_width=True, key="reset_all_modules"):
                st.session_state.logging_update_in_progress = True
                for module in list(module_levels.keys()):
                    reset_module_level(module)
                st.rerun()

    with log_tab3:
        # Test section - MODIFIED to prevent infinite loops
        st.markdown("##### 🧪 Test Logging")

        col_test1, col_test2 = st.columns(2)

        with col_test1:
            # Only show test button if we're not in an update
            test_button_disabled = st.session_state.logging_update_in_progress

            if st.button("📝 Send Test Messages", use_container_width=True,
                        disabled=test_button_disabled, key="send_test_logs_btn"):

                # Temporarily disable the update flag to prevent loops
                original_flag = st.session_state.logging_update_in_progress
                st.session_state.logging_update_in_progress = True

                if current_disengaged:
                    st.info("Logging is disengaged - these messages will be IGNORED")
                    # Use a special flag to prevent these logs from triggering UI updates
                    debug("Debug test - should NOT appear")
                    info("Info test - should NOT appear")
                    warning("Warning test - should NOT appear")
                    error("Error test - should NOT appear")
                    st.success("Test messages sent (they were ignored)")
                else:
                    st.info(f"Logging is engaged (level: {current_global_level}) - check console/logs")
                    debug("🔍 DEBUG: This is a debug message from admin UI")
                    info("ℹ️ INFO: This is an info message from admin UI")
                    warning("⚠️ WARNING: This is a warning message from admin UI")
                    error("❌ ERROR: This is an error message from admin UI")
                    st.success("Test messages sent - check your logs")

                # Restore flag
                st.session_state.logging_update_in_progress = original_flag

        with col_test2:
            if st.button("🧹 Clear All Module Levels", use_container_width=True, key="clear_all_modules_btn"):
                st.session_state.logging_update_in_progress = True
                for module in list(module_levels.keys()):
                    reset_module_level(module)
                st.rerun()

        # Show current configuration summary
        with st.expander("📋 Current Logging Configuration", expanded=False):
            st.json({
                "disengaged": current_disengaged,
                "global_level": current_global_level,
                "module_levels": module_levels,
                "update_in_progress": st.session_state.logging_update_in_progress,
            })

    # Clear the update flag at the end of the function if it was set
    # This ensures we don't get stuck in update mode
    if st.session_state.logging_update_in_progress:
        # Only clear if we're not in the middle of a button action
        # We can detect this by checking if any button was just clicked
        button_clicked = any([
            st.session_state.get('add_module_level_btn', False),
            st.session_state.get('preset_all_debug', False),
            st.session_state.get('preset_all_info', False),
            st.session_state.get('preset_all_warning', False),
            st.session_state.get('reset_all_modules', False),
        ])

        if not button_clicked:
            st.session_state.logging_update_in_progress = False

    st.divider()

    # SECTION 2: Configuration Inspection (existing code)
    st.subheader("📁 Configuration Inspection")

    config = get_config()

    # Check for debug module configuration
    debug_config = config.get("debug", {})

    if not debug_config:
        st.warning("⚠️ Debug configuration not found! The 'debug' section is missing from the configuration.")
        st.info("Make sure your CONFIG_FILE has a 'debug' section or that the debug module's config was loaded.")
    else:
        # Check specific debug configuration keys
        missing_keys = []
        expected_keys = ["enabled", "log_level", "show_environment_info",
                        "show_database_info", "show_module_info"]

        for key in expected_keys:
            if key not in debug_config:
                missing_keys.append(key)

        if missing_keys:
            st.warning(f"⚠️ Some debug configuration keys are missing: {', '.join(missing_keys)}")
        else:
            st.success("✅ Debug configuration is fully loaded and valid!")

            # Show debug config status
            col_enabled, col_log = st.columns(2)
            with col_enabled:
                enabled = debug_config.get("enabled", False)
                status = "🟢 ENABLED" if enabled else "🔴 DISABLED"
                st.metric("Debug Module", status)

            with col_log:
                log_level = debug_config.get("log_level", "INFO")
                st.metric("Log Level", log_level)

    st.divider()

    # File-centric config registry display (existing code)
    st.subheader("📁 Config registry by file")

    if hasattr(config, 'list_source_files') and hasattr(config, 'list_keys_by_source_file'):
        source_files = config.list_source_files()
        keys_by_file = config.list_keys_by_source_file()

        if not source_files:
            st.info("No configuration files have been loaded yet.")
        else:
            st.caption(f"Loaded config files: {len(source_files)}")

            selected_file = st.selectbox(
                "Select a config file",
                options=source_files,
                key="debug_config_file_selector",
            )

            file_keys = keys_by_file.get(selected_file, [])
            st.code(selected_file)
            st.caption(f"Keys in file: {len(file_keys)}")

            if file_keys:
                rows = [
                    {
                        "key": key,
                        "value": str(config.get(key)),
                    }
                    for key in file_keys
                ]
                st.dataframe(rows, width='stretch', hide_index=True)
            else:
                st.info("No leaf keys tracked for this file.")

            with st.expander("🗂️ All files → keys", expanded=False):
                st.json(keys_by_file)
    else:
        st.warning("Config source registry APIs are not available.")


def show_ui_registry_tab():
    """Tab 3: UI Registry Inspection."""
    st.header("🎯 UI Registry Inspection")

    if not UI_REGISTRY_AVAILABLE:
        st.error("UI Registry is not available!")
        return

    ui_registry = st.session_state.ui_registry

    # Get injection point data
    all_points = ui_registry.get_all_injection_points()
    stats = ui_registry.get_injection_point_stats()

    # Summary
    col_summary1, col_summary2, col_summary3 = st.columns(3)

    with col_summary1:
        st.metric("Injection Points", len(all_points))

    with col_summary2:
        st.metric("Active UI Modules", len(ui_registry.modules))

    with col_summary3:
        if stats:
            total_functions = sum(stats.values())
            st.metric("Total Functions", total_functions)

    st.divider()

    # Create two columns for better display
    col_stats, col_list = st.columns(2)

    with col_stats:
        st.markdown("##### 📊 Statistics")
        if stats:
            # Create a simple table
            st.markdown("| Injection Point | Modules |")
            st.markdown("|----------------|---------|")
            for point, count in sorted(stats.items()):
                st.markdown(f"| `{point}` | {count} |")
        else:
            st.info("No statistics available")

    with col_list:
        st.markdown("##### 📝 All Points")
        if all_points:
            # List all injection points
            st.markdown("<ul>", unsafe_allow_html=True)
            for point in sorted(all_points):
                st.markdown(f"<li><code>{point}</code></li>", unsafe_allow_html=True)
            st.markdown("</ul>", unsafe_allow_html=True)
        else:
            st.info("No injection points registered")

    # Detailed module information in an expander
    with st.expander("🔍 Module Details", expanded=False):
        if ui_registry.modules:
            # Get active modules from module handler
            active_modules = set()
            if ui_registry.module_handler:
                active_modules = set(ui_registry.module_handler.get_active_modules())

            for module_key, module_info in ui_registry.modules.items():
                is_shared = module_info.get('is_shared', False)
                base_name = module_info.get('base_name', 'unknown')
                render_funcs = module_info.get('render_functions', {})

                # Determine if module should be active
                if is_shared:
                    status = "🟢 SHARED"
                elif base_name in active_modules:
                    status = "🟢 ACTIVE"
                else:
                    status = "🔴 INACTIVE"

                st.markdown(f"**{module_key}** {status}")
                st.caption(f"Path: {module_info.get('path', 'N/A')}")

                if render_funcs:
                    st.write(f"Injection points: {', '.join(sorted(render_funcs.keys()))}")
                else:
                    st.write("No render functions")
                st.divider()
        else:
            st.info("No UI modules registered")

    # Test new injection point creation
    with st.expander("🧪 Test New Injection Point", expanded=False):
        st.markdown("Test creating a new injection point dynamically.")

        test_point_name = st.text_input(
            "Test injection point name:",
            value="test_custom_point",
            help="Enter a name for a test injection point (will be prefixed with 'inject_ui_')"
        )

        col_test1, col_test2 = st.columns(2)

        with col_test1:
            if st.button("Register Test Point", width='stretch'):
                # This simulates what would happen when a module registers a new point
                # In reality, modules would define functions like inject_ui_test_custom_point
                st.info(f"To create injection point '{test_point_name}', a module should define a function named:")
                st.code(f"def inject_ui_{test_point_name}():")
                st.code(f"    # Implementation")
                st.code(f"    return 'Content for {test_point_name}'")

        with col_test2:
            if st.button("Check Current Points", width='stretch'):
                # Refresh and show updated list
                current_points = ui_registry.get_all_injection_points()
                st.info(f"Currently have {len(current_points)} injection points")
                st.write("First 5:", current_points[:5] if len(current_points) > 5 else current_points)


def show_quick_tests_tab():
    """Tab 4: Quick Tests and System Info."""
    st.header("⚡ Quick Tests & System Info")

    # Section 1: Current User Info
    st.subheader("👤 Current User")
    if st.session_state.get('current_user'):
        user = st.session_state.current_user
        col_user1, col_user2 = st.columns(2)

        with col_user1:
            st.metric("User Name", user.get('name', 'N/A'))
            st.metric("User ID", user.get('id', 'N/A'))

        with col_user2:
            st.metric("Email", user.get('email', 'N/A'))
            status = "🟢 ACTIVE" if user.get('is_active', True) else "🔴 INACTIVE"
            st.metric("Status", status)

        if user.get('profile'):
            st.write("**Profile:**")
            profile = user['profile']
            st.write(f"  - Role: {profile.get('role', 'N/A')}")
            st.write(f"  - Rights: {', '.join(profile.get('rights', []))}")
    else:
        st.warning("No user currently logged in")

    st.divider()

    # Section 2: Quick Test Buttons
    st.subheader("⚡ Quick Tests")

    col5, col6, col7 = st.columns(3)

    with col5:
        if st.button("Test User Count", width='stretch'):
            try:
                user_count = get_user_manager().get_user_count()
                st.session_state.debug_test_result = f"Total users in system: {user_count}"
                st.success(f"✅ User count: {user_count}")
                log("info", f"User count test: {user_count} users")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    with col6:
        if st.button("Test Logging", width='stretch'):
            log("info", "Test log message from debug admin panel")
            log("debug", "Debug test message")
            log("warning", "Warning test message")
            log("error", "Error test message (simulated)")
            st.success("✅ Test logs sent to all levels")
            st.session_state.debug_test_result = "Test log messages sent. Check logs."

    with col7:
        if st.button("Session Info", width='stretch'):
            session_keys = list(st.session_state.keys())
            session_info = f"Session has {len(session_keys)} keys:\n"
            for key in sorted(session_keys):
                if not key.startswith('_'):
                    value = st.session_state.get(key)
                    value_type = type(value).__name__
                    session_info += f"- {key}: {value_type}\n"

            st.session_state.debug_test_result = session_info
            st.success(f"✅ Session info: {len(session_keys)} keys")

    st.divider()

    # Section 3: Session State Overview
    st.subheader("💾 Session State")

    if st.button("Refresh Session Info", key="refresh_session"):
        st.rerun()

    session_keys = [k for k in st.session_state.keys() if not k.startswith('_')]

    if session_keys:
        st.write(f"**Total session keys:** {len(session_keys)}")

        # Group keys by prefix
        key_groups = {}
        for key in sorted(session_keys):
            prefix = key.split('_')[0] if '_' in key else 'other'
            if prefix not in key_groups:
                key_groups[prefix] = []
            key_groups[prefix].append(key)

        # Display in columns
        cols = st.columns(min(3, len(key_groups)))
        col_idx = 0

        for prefix, keys in sorted(key_groups.items()):
            with cols[col_idx % len(cols)]:
                with st.expander(f"{prefix.upper()} ({len(keys)})", expanded=False):
                    for key in keys:
                        value = st.session_state.get(key)
                        value_type = type(value).__name__
                        value_preview = str(value)[:50] + "..." if len(str(value)) > 50 else str(value)
                        st.caption(f"**{key}** ({value_type}): {value_preview}")
            col_idx += 1
    else:
        st.info("No session state keys found")

    st.divider()

    # Section 4: Reset All
    st.subheader("🔄 Reset")

    if st.button("Reset All Debug Data", type="secondary", width='stretch'):
        st.session_state.debug_test_text = ""
        st.session_state.debug_test_result = ""
        st.session_state.debug_llm_response = ""
        st.session_state.debug_llm_loading = False
        st.success("✅ All debug data cleared!")
        st.rerun()


# Dans debug_admin_ui.py, modifiez la fonction show_debug_admin_content:

def _get_db_reset_code(user_id: str) -> Optional[str]:
    """Fetch the current reset_code for a user directly from the DB (admin use only)."""
    try:
        from core.database import get_db_manager
        from sqlalchemy import text
        db = get_db_manager()
        with db.get_session() as session:
            row = session.execute(
                text("SELECT reset_code FROM users WHERE id = :uid"),
                {"uid": user_id},
            ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


def show_mailerlite_tab():
    """Tab: MailerLite diagnostics."""
    import os
    import requests as _requests
    from shared.mailer_lite import get_groups, get_configured_group_id
    from st_shared.cached import get_config

    st.subheader("MailerLite Diagnostics")

    token = os.getenv("MAILER_LITE_API")
    group_id = get_configured_group_id()
    server_ip = None

    # ── Status row ──────────────────────────────────────────────────────────
    col1, col2 = st.columns(2)
    with col1:
        st.text("MAILER_LITE_API")
        if token:
            masked = token[:6] + "…" + token[-4:]
            st.success(f"Set ({masked})")
        else:
            st.error("Not set")

    with col2:
        st.text("Server public IP")
        try:
            ip_resp = _requests.get("https://api.ipify.org", timeout=5)
            server_ip = ip_resp.text.strip()
            st.info(server_ip)
        except Exception as e:
            st.warning(f"Could not detect: {e}")

    st.divider()

    # ── Connection test ──────────────────────────────────────────────────────
    st.markdown("**Test API connection**")
    if st.button("Ping MailerLite", disabled=not token):
        try:
            resp = _requests.get(
                "https://connect.mailerlite.com/api/subscribers?limit=1",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                timeout=8,
            )
            if resp.status_code == 200:
                total = resp.json().get("meta", {}).get("total", "?")
                st.success(f"Connected (200) — {total} subscriber(s) in your account")
            elif resp.status_code == 403:
                st.error(f"403 Forbidden — add server IP {server_ip or '?'} to the MailerLite allowlist (see below)")
            elif resp.status_code == 401:
                st.error("401 Unauthorized — check MAILER_LITE_API value")
            else:
                st.warning(f"Status {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            st.error(f"Request failed: {e}")

    st.divider()

    # ── Group selection ──────────────────────────────────────────────────────
    st.markdown("**Subscriber group**")
    st.caption("Subscribers added to the selected group trigger your MailerLite automation.")

    if "ml_groups_cache" not in st.session_state:
        st.session_state.ml_groups_cache = []

    col_load, col_status = st.columns([1, 3])
    with col_load:
        if st.button("Load groups", disabled=not token, key="ml_load_groups"):
            groups = get_groups()
            st.session_state.ml_groups_cache = groups
            if not groups:
                st.warning("No groups found. Create one in app.mailerlite.com first.")

    groups = st.session_state.ml_groups_cache
    if groups:
        group_opts = {g["id"]: f"{g['name']} (id: {g['id']})" for g in groups}
        none_option = "__none__"
        group_opts_with_none = {none_option: "— no group —", **group_opts}

        current_selection = group_id if group_id in group_opts else none_option
        selected_gid = st.selectbox(
            "Select group",
            options=list(group_opts_with_none.keys()),
            format_func=lambda x: group_opts_with_none[x],
            index=list(group_opts_with_none.keys()).index(current_selection),
            key="ml_group_selectbox",
        )

        save_col, status_col = st.columns([1, 3])
        with save_col:
            if st.button("Save selection", key="ml_save_group"):
                value = selected_gid if selected_gid != none_option else None
                get_config().save_key("mailer_lite.group_id", value)
                group_id = value
                st.success("Saved." if value else "Group cleared.")
                st.rerun()
        with status_col:
            if group_id:
                name = group_opts.get(group_id, group_id)
                st.info(f"Active group: **{name}**")
            else:
                st.warning("No group selected — automation will not trigger.")
    elif not token:
        st.info("Set MAILER_LITE_API first, then load groups.")
    else:
        st.info("Click 'Load groups' to fetch your MailerLite groups.")

    st.divider()

    # ── Test email ───────────────────────────────────────────────────────────
    st.markdown("**Send a test welcome email**")

    if not group_id:
        st.warning("No group selected — automation won't fire.")

    st.info(
        "**MailerLite template variable syntax:**\n"
        "- New drag-and-drop builder: `{{ subscriber.fields.reset_code }}`\n"
        "- Classic / HTML builder: `{$reset_code}`\n\n"
        "Use whichever matches your builder. The field key in both cases must be exactly `reset_code`."
    )

    user_manager = get_user_manager()
    all_users = user_manager.get_all_users()
    users_with_email = [u for u in all_users if u.get("email")]

    if not users_with_email:
        st.info("No users with email addresses found.")
    else:
        user_opts_map = {u["id"]: f"{u['name']} <{u['email']}>" for u in users_with_email}
        selected_uid = st.selectbox(
            "Target user",
            options=list(user_opts_map.keys()),
            format_func=lambda x: user_opts_map[x],
            key="ml_test_email_target",
        )
        target = next(u for u in users_with_email if u["id"] == selected_uid)

        # Look up real reset_code from DB
        real_code = _get_db_reset_code(target["id"])
        if real_code:
            st.success(f"DB reset_code found for this user: `{real_code[:8]}…`")
        else:
            st.warning(
                "This user has no reset_code in the DB. "
                "Use the Forgot Password flow on their account to generate one first, "
                "or pick a user created by the webhook simulator."
            )

        col_send, col_reset = st.columns(2)

        with col_send:
            if st.button("Send test (real code)", disabled=not token or not real_code, key="ml_send_test"):
                from shared.mailer_lite import notify_account_approved
                ml_ok, ml_diag = notify_account_approved(
                    email=target["email"],
                    user_name=target.get("name", ""),
                    reset_code=real_code,
                )
                if ml_ok:
                    if group_id:
                        st.success(
                            f"Subscriber upserted for **{target['email']}**, "
                            f"added to group `{group_id}`, "
                            f"`reset_code` field = `{real_code[:8]}…`"
                        )
                        st.caption(
                            "Check your inbox. If the template shows the literal variable "
                            "instead of the code, verify the template syntax (see above) "
                            "and that the MailerLite field key is exactly `reset_code`."
                        )
                    else:
                        st.warning("Upserted but no group — automation won't fire.")
                    st.json(ml_diag)
                else:
                    st.error(f"Failed: {ml_diag.get('error', '?')}")
                    st.json(ml_diag)

        with col_reset:
            st.caption("Already subscribed? Remove from group so the automation re-fires:")
            if st.button("Remove from group", disabled=not token or not group_id, key="ml_remove_group"):
                from shared.mailer_lite import get_subscriber_by_email, remove_subscriber_from_group
                sub = get_subscriber_by_email(target["email"])
                if not sub:
                    st.warning(f"Subscriber {target['email']} not found in MailerLite.")
                else:
                    ok, msg = remove_subscriber_from_group(sub["id"], group_id)
                    if ok:
                        st.success(
                            f"Removed **{target['email']}** from group `{group_id}`. "
                            "You can now re-send the test and the automation will fire again."
                        )
                    else:
                        st.error(f"Failed: {msg}")

    st.divider()

    # ── Transactional email (MailerSend) ─────────────────────────────────────
    st.markdown("**Transactional email — MailerSend**")
    st.caption(
        "Used to send welcome emails with the reset code when a user is created via webhook. "
        "Free tier: 3,000 emails/month. Requires a verified sending domain."
    )

    ms_key = os.getenv("BREVO_API_KEY")
    ms_from = os.getenv("BREVO_FROM")
    ms_from_name = os.getenv("BREVO_FROM_NAME", ms_from or "")
    app_url = os.getenv("APP_URL", "")

    col_ms1, col_ms2, col_ms3 = st.columns(3)
    with col_ms1:
        st.text("BREVO_API_KEY")
        if ms_key:
            st.success(ms_key[:6] + "…" + ms_key[-4:])
        else:
            st.error("Not set")
    with col_ms2:
        st.text("BREVO_FROM")
        if ms_from:
            st.success(ms_from)
        else:
            st.error("Not set")
    with col_ms3:
        st.text("APP_URL")
        if app_url:
            st.success(app_url)
        else:
            st.warning("Not set — login link won't appear in email")

    if ms_key and ms_from:
        st.markdown("**Send a test welcome email with reset code**")
        user_manager_ms = get_user_manager()
        ms_users = [u for u in user_manager_ms.get_all_users() if u.get("email")]

        if ms_users:
            ms_user_opts = {u["id"]: f"{u['name']} <{u['email']}>" for u in ms_users}
            ms_selected_uid = st.selectbox(
                "Target user",
                options=list(ms_user_opts.keys()),
                format_func=lambda x: ms_user_opts[x],
                key="ms_test_target",
            )
            ms_target = next(u for u in ms_users if u["id"] == ms_selected_uid)

            if st.button("Send test welcome email", key="ms_send_test"):
                from shared.transactional_email import send_welcome_reset_code
                fake_code = "TEST-RESET-CODE-1234"
                success, msg = send_welcome_reset_code(
                    to_email=ms_target["email"],
                    to_name=ms_target.get("name", "User"),
                    reset_code=fake_code,
                )
                if success:
                    st.success(
                        f"Email queued for **{ms_target['email']}**. "
                        f"The email contains reset code `{fake_code}` — use it to verify the template looks correct."
                    )
                else:
                    st.error(f"Failed: {msg}")
        else:
            st.info("No users with email addresses found.")
    else:
        st.info("Set BREVO_API_KEY and BREVO_FROM to enable transactional email testing.")

    st.divider()

    st.markdown("**IP allowlist — how to fix 403 errors**")
    st.info(
        "1. Log in to **app.mailerlite.com**\n"
        "2. Go to **Integrations → Developer API**\n"
        "3. Under *API settings*, find **Allowed IP addresses**\n"
        f"4. Add `{server_ip or '<your server IP>'}` and click **Save**"
    )


def show_debug_admin_content():
    """Main function to display the Debug Admin with tabs."""
    st.header("🔧 Debug and Testing")

    # Create tabs
    tab1, tab2, tab3, tab4, tab5, tab6, tab7 = st.tabs([
        "📝 Text & LLM",
        "⚙️ Config",
        "🎯 UI Registry",
        "⚡ Quick Tests",
        "⏱️ Profiler",
        "📊 Memory",
        "📧 MailerLite",
    ])

    with tab1:
        show_text_llm_tab()

    with tab2:
        show_config_tab()

    with tab3:
        show_ui_registry_tab()

    with tab4:
        show_quick_tests_tab()

    with tab5:
        show_profiler_tab()

    with tab6:
        # Only load memory tab when selected
        if 'memory_tab_loaded' not in st.session_state:
            st.session_state.memory_tab_loaded = False

        if not st.session_state.memory_tab_loaded:
            if st.button("📊 Load Memory Analysis (may be slow)", width='stretch', type="primary"):
                st.session_state.memory_tab_loaded = True
                st.rerun()
        else:
            from modules.debug.debug_mem_tab import show_memory_tab
            show_memory_tab()

            if st.button("🔄 Reload", width='stretch'):
                st.rerun()

    with tab7:
        show_mailerlite_tab()

def inject_ui_admin_tab():
    """Register the Debug admin tab using the new injection mechanism.
    Returns: (tab_name, render_function) tuple."""
    return ("Debug", show_debug_admin_content)


def inject_ui_initialize():
    """Initialize the debug admin UI module."""
    # Initialize session state variables
    if "debug_test_text" not in st.session_state:
        st.session_state.debug_test_text = ""
    if "debug_test_result" not in st.session_state:
        st.session_state.debug_test_result = ""
    if "debug_llm_response" not in st.session_state:
        st.session_state.debug_llm_response = ""
    if "debug_llm_loading" not in st.session_state:
        st.session_state.debug_llm_loading = False

    log("debug", "Debug admin UI initialized")

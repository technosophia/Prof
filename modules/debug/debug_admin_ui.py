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
from shared.common import _, log, get_config
from shared.llm import llm_generate, get_current_llm_info
from shared.users import user_manager


# Try to import ui_registry for injection point debugging
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
        if st.button("📤 Display Text", use_container_width=True):
            if test_text.strip():
                st.session_state.debug_test_result = test_text
                st.success("Text captured! Check the result section below.")
                log("debug", f"Debug text captured: {test_text[:50]}...")
            else:
                st.warning("Please enter some text first")

    with col2:
        # Button to clear text
        if st.button("🗑️ Clear Text", use_container_width=True, type="secondary"):
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
            if st.button("💭 Ask LLM", use_container_width=True, type="primary"):
                if llm_question.strip():
                    st.session_state.debug_llm_loading = True
                    st.rerun()
                else:
                    st.warning("Please enter a question")

        with col4:
            # Button to clear LLM response
            if st.button("🗑️ Clear Response", use_container_width=True, type="secondary"):
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
                        llm_generate(
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
                log("error", error_msg, exc_info=True)
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
    """Tab 2: Configuration Inspection."""
    st.header("⚙️ Configuration Inspection")

    config = get_config()

    # Check for debug module configuration
    debug_config = config.get("modules.debug", {})

    if not debug_config:
        st.warning("⚠️ Debug configuration not found! The 'debug' section is missing from the configuration.")
        st.info("Make sure your config.json has a 'debug' section or that the debug module's config was loaded.")
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

    # Display all configuration sections
    st.subheader("📋 All Configuration Sections")

    # Get all top-level keys in configuration
    config_dict = config._config if hasattr(config, '_config') else {}

    if config_dict:
        # Create tabs for each main section
        section_names = list(config_dict.keys())
        config_tabs = st.tabs(section_names)

        for i, section_name in enumerate(section_names):
            with config_tabs[i]:
                section_data = config_dict.get(section_name, {})

                if section_name == "debug":
                    st.info("🔄 This is the debug module configuration")

                # Display as JSON
                st.json(section_data)

                # Show metadata if available
                if hasattr(config, '_modules'):
                    for module_name, module_config in config._modules.items():
                        if section_name in module_config:
                            st.caption(f"📍 Source: Module '{module_name}'")

                # Show raw value count
                def count_values(obj):
                    if isinstance(obj, dict):
                        total = 0
                        for key, value in obj.items():
                            total += count_values(value)
                        return total
                    else:
                        return 1

                value_count = count_values(section_data)
                st.caption(f"Contains {value_count} configuration values")
    else:
        st.warning("No configuration data found!")

    st.divider()

    # Show loaded configuration files
    st.subheader("📁 Loaded Configuration Files")

    if hasattr(config, '_loaded_files'):
        loaded_files = config._loaded_files

        if loaded_files:
            st.write(f"**Total files loaded:** {len(loaded_files)}")

            for filepath, timestamp in loaded_files.items():
                col_file, col_time = st.columns([3, 1])
                with col_file:
                    st.code(filepath)
                with col_time:
                    st.caption(timestamp.strftime("%H:%M:%S"))
        else:
            st.info("No configuration files have been loaded yet")
    else:
        st.warning("Loaded files tracking not available")

    # Show module configurations
    st.divider()
    st.subheader("🧩 Module Configurations")

    if hasattr(config, '_modules'):
        modules = config._modules

        if modules:
            st.write(f"**Modules with config:** {len(modules)}")

            for module_name, module_config in modules.items():
                with st.expander(f"📦 {module_name}", expanded=False):
                    st.json(module_config)

                    # Count keys in this module
                    def count_keys(obj):
                        if isinstance(obj, dict):
                            count = 0
                            for key, value in obj.items():
                                count += 1  # Count this key
                                count += count_keys(value)  # Count nested keys
                            return count
                        return 0

                    key_count = count_keys(module_config)
                    st.caption(f"Contains {key_count} configuration keys")
        else:
            st.info("No module configurations have been injected")
    else:
        st.warning("Module configuration tracking not available")


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
            if st.button("Register Test Point", use_container_width=True):
                # This simulates what would happen when a module registers a new point
                # In reality, modules would define functions like inject_ui_test_custom_point
                st.info(f"To create injection point '{test_point_name}', a module should define a function named:")
                st.code(f"def inject_ui_{test_point_name}():")
                st.code(f"    # Implementation")
                st.code(f"    return 'Content for {test_point_name}'")

        with col_test2:
            if st.button("Check Current Points", use_container_width=True):
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
        if st.button("Test User Count", use_container_width=True):
            try:
                user_count = user_manager.get_user_count()
                st.session_state.debug_test_result = f"Total users in system: {user_count}"
                st.success(f"✅ User count: {user_count}")
                log("info", f"User count test: {user_count} users")
            except Exception as e:
                st.error(f"❌ Error: {str(e)}")

    with col6:
        if st.button("Test Logging", use_container_width=True):
            log("info", "Test log message from debug admin panel")
            log("debug", "Debug test message")
            log("warning", "Warning test message")
            log("error", "Error test message (simulated)")
            st.success("✅ Test logs sent to all levels")
            st.session_state.debug_test_result = "Test log messages sent. Check logs."

    with col7:
        if st.button("Session Info", use_container_width=True):
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

    if st.button("Reset All Debug Data", type="secondary", use_container_width=True):
        st.session_state.debug_test_text = ""
        st.session_state.debug_test_result = ""
        st.session_state.debug_llm_response = ""
        st.session_state.debug_llm_loading = False
        st.success("✅ All debug data cleared!")
        st.rerun()


def show_debug_admin_content():
    """Main function to display the Debug Admin with tabs."""
    st.header("🔧 Debug and Testing")

    # Create tabs
    tab1, tab2, tab3, tab4 = st.tabs([
        "📝 Text & LLM",
        "⚙️ Config",
        "🎯 UI Registry",
        "⚡ Quick Tests"
    ])

    with tab1:
        show_text_llm_tab()

    with tab2:
        show_config_tab()

    with tab3:
        show_ui_registry_tab()

    with tab4:
        show_quick_tests_tab()


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

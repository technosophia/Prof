# file name: shared/prompt_manager_ui.py
"""
Prompt Manager UI Module

Provides admin interface for viewing and managing all prompts across modules.
Supports both legacy and multilingual prompt formats.
"""

import streamlit as st
import yaml
from shared.common import (
    _, log, get_prompt, get_all_prompts, get_module_prompts,
    list_modules_with_prompts, is_multilingual,
    set_default_language, get_prompt_manager,
    get_available_prompt_languages  # FIXED: Import the correct function
)


def format_prompt_for_display(prompt_value, prompt_path="", max_height=400, language=None):
    """Format a prompt value for display in Streamlit."""
    # Create a unique key based on the path and language
    lang_suffix = f"_{language}" if language else ""
    key = f"prompt_display_{prompt_path.replace('.', '_')}{lang_suffix}"

    if isinstance(prompt_value, str):
        height = min(max_height, max(100, len(prompt_value) // 4))
        return st.text_area(
            "Prompt Content:",
            value=prompt_value,
            height=height,
            key=key,
            disabled=True
        )
    elif isinstance(prompt_value, dict):
        yaml_str = yaml.dump(prompt_value, default_flow_style=False, allow_unicode=True, indent=2)
        return st.code(yaml_str, language="yaml")
    elif isinstance(prompt_value, list):
        for i, item in enumerate(prompt_value):
            st.markdown(f"- {item}")
        return None
    else:
        return st.write(prompt_value, key=key)


def show_prompt_admin_content():
    """Display the Prompt Manager admin content."""
    st.title("📝 Prompt Manager")

    # Check if multilingual mode is active
    multilingual = is_multilingual()
    # FIXED: Use get_available_prompt_languages() instead of get_available_languages()
    available_langs = get_available_prompt_languages() if multilingual else []

    if multilingual:
        st.caption(f"🌐 Multilingual Mode | Available languages: {', '.join(available_langs)}")
    else:
        st.caption("📄 Legacy Mode (Single Language)")

    # Language selector for multilingual mode
    selected_language = None
    if multilingual and available_langs:
        col1, col2 = st.columns([2, 1])
        with col1:
            selected_language = st.selectbox(
                "🌐 Select Language:",
                options=available_langs,
                index=available_langs.index('en') if 'en' in available_langs else 0,
                help="Choose a language to view prompts"
            )
        with col2:
            if st.button("Set as Default", width='stretch'):
                set_default_language(selected_language)
                st.success(f"Default language set to {selected_language}")
                st.rerun()

    # Get modules for selected language
    if multilingual:
        modules = list_modules_with_prompts(selected_language)
    else:
        modules = list_modules_with_prompts()

    # Debug: Log what we found
    log("info", f"Multilingual mode: {multilingual}, Available languages: {available_langs}, Modules: {modules}, Selected language: {selected_language}")

    if not modules:
        if multilingual:
            st.info(f"No prompts found for language '{selected_language}'. Make sure modules have prompts.{selected_language}.yaml files.")
        else:
            st.info("No prompts found. Make sure modules have prompts.yaml files.")

        # Show debug info
        with st.expander("Debug Information"):
            st.write("Multilingual mode:", multilingual)
            st.write("Available prompt languages:", available_langs)
            st.write("Selected language:", selected_language)
            st.write("Modules found:", modules)

            # Try to get prompts directly to see what's loaded
            try:
                all_prompts = get_all_prompts(selected_language if multilingual else None)
                st.write("All prompts structure:", all_prompts)
            except Exception as e:
                st.write("Error getting prompts:", str(e))

        with st.expander("🔧 Debug Prompt Manager State", expanded=False):
            debug_prompt_manager_state()

        return

    # Module selector
    st.header("Module Selection")

    col1, col2 = st.columns([3, 1])
    with col1:
        selected_module = st.selectbox(
            "Select a module:",
            options=modules,
            help="Choose a module to view its prompts"
        )

    with col2:
        st.write("")  # Spacing
        if st.button("🔄 Refresh", width='stretch'):
            st.rerun()

    if selected_module:
        # Get module prompts
        module_prompts = get_module_prompts(selected_module, selected_language if multilingual else None)

        if not module_prompts:
            if multilingual:
                st.info(f"No prompts found for module '{selected_module}' in language '{selected_language}'.")
            else:
                st.info(f"No prompts found for module '{selected_module}'.")
            return

        # Display module info
        lang_suffix = f" ({selected_language})" if multilingual and selected_language else ""
        st.header(f"Module: {selected_module}{lang_suffix}")

        # Source file info
        prompt_manager = get_prompt_manager()
        source_file = prompt_manager.get_source_file(
            selected_module,
            selected_language if multilingual else None
        )
        if source_file:
            st.caption(f"📁 Source: `{source_file}`")

        # Create tabs for different views
        tab1, tab2, tab3 = st.tabs(["📄 Tree View", "📋 List View", "📊 Statistics"])

        with tab1:
            # Tree view (expandable sections)
            st.subheader("Prompt Tree View")

            def display_prompt_tree(data: dict, path: str = "", depth: int = 0):
                if not data:
                    return

                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key
                    indent = "&nbsp;" * (depth * 4)

                    if isinstance(value, dict):
                        with st.expander(f"{indent}📁 **{key}**", expanded=depth < 2):
                            display_prompt_tree(value, current_path, depth + 1)
                    else:
                        st.markdown(f"{indent}**{key}**")
                        format_prompt_for_display(value, f'tree_{current_path}', language=selected_language)
                        st.divider()

            display_prompt_tree(module_prompts)

        with tab2:
            # List view (flat list of all prompts with keys)
            st.subheader("All Prompts (Flat List)")

            def flatten_prompts(data: dict, prefix: str = ""):
                flat = {}
                for key, value in data.items():
                    full_key = f"{prefix}.{key}" if prefix else key
                    if isinstance(value, dict):
                        flat.update(flatten_prompts(value, full_key))
                    else:
                        flat[full_key] = value
                return flat

            flat_prompts = flatten_prompts(module_prompts)

            if flat_prompts:
                for key in sorted(flat_prompts.keys()):
                    with st.expander(f"🔑 `{key}`", expanded=False):
                        st.code(key, language="text")
                        format_prompt_for_display(flat_prompts[key], f'list_{key}', language=selected_language)
            else:
                st.info("No leaf prompts found in this module.")

        with tab3:
            # Statistics
            st.subheader("Module Statistics")

            def count_prompts(data: dict) -> tuple[int, int]:
                leaf_count = 0
                total_count = 0

                for value in data.values():
                    total_count += 1
                    if isinstance(value, dict):
                        sub_leaves, sub_total = count_prompts(value)
                        leaf_count += sub_leaves
                        total_count += sub_total
                    else:
                        leaf_count += 1

                return leaf_count, total_count

            leaf_count, total_count = count_prompts(module_prompts)

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Leaf Prompts", leaf_count)
            with col2:
                st.metric("Total Nodes", total_count)
            with col3:
                st.metric("Nesting Levels", total_count - leaf_count)

            if leaf_count > 0:
                # Prompt types distribution
                st.subheader("Prompt Types")

                def analyze_types(data: dict):
                    types = {}
                    for value in data.values():
                        if isinstance(value, dict):
                            sub_types = analyze_types(value)
                            for type_name, count in sub_types.items():
                                types[type_name] = types.get(type_name, 0) + count
                        else:
                            type_name = type(value).__name__
                            types[type_name] = types.get(type_name, 0) + 1
                    return types

                type_distribution = analyze_types(module_prompts)

                for type_name, count in sorted(type_distribution.items()):
                    st.progress(
                        count / leaf_count,
                        text=f"{type_name}: {count} prompts"
                    )
            else:
                st.info("No leaf prompts to analyze.")

        # Export section
        st.header("Export Options")

        col1, col2 = st.columns(2)

        with col1:
            file_suffix = f"_{selected_language}" if multilingual and selected_language else ""
            yaml_data = yaml.dump(
                module_prompts,
                default_flow_style=False,
                allow_unicode=True,
                indent=2,
                sort_keys=True
            )

            st.download_button(
                label="📥 Export as YAML",
                data=yaml_data,
                file_name=f"{selected_module}{file_suffix}_prompts.yaml",
                mime="text/yaml",
                width='stretch'
            )

        with col2:
            if st.button("📋 Show YAML", width='stretch'):
                yaml_data = yaml.dump(
                    module_prompts,
                    default_flow_style=False,
                    allow_unicode=True,
                    indent=2,
                    sort_keys=True
                )
                st.code(yaml_data, language="yaml")

    # Global statistics at the bottom
    st.divider()
    st.subheader("🌐 Global Statistics")

    col1, col2, col3 = st.columns(3)

    with col1:
        if multilingual:
            # Collect all module names across all languages into a single set
            all_modules = set()
            for lang in available_langs:
                modules_for_lang = list_modules_with_prompts(lang)
                all_modules.update(modules_for_lang)
            st.metric("Total Modules (all languages)", len(all_modules))
        else:
            st.metric("Total Modules", len(modules))

    with col2:
        if multilingual:
            # Count total leaf prompts across all languages
            total_leaf_prompts = 0
            for lang in available_langs:
                for module in list_modules_with_prompts(lang):
                    module_data = get_module_prompts(module, lang)
                    if module_data:
                        def count_leaves(data: dict):
                            count = 0
                            for value in data.values():
                                if isinstance(value, dict):
                                    count += count_leaves(value)
                                else:
                                    count += 1
                            return count
                        total_leaf_prompts += count_leaves(module_data)

            st.metric("Total Prompts (all languages)", total_leaf_prompts)
        else:
            total_leaf_prompts = 0
            for module in modules:
                module_data = get_module_prompts(module)
                if module_data:
                    def count_leaves(data: dict):
                        count = 0
                        for value in data.values():
                            if isinstance(value, dict):
                                count += count_leaves(value)
                            else:
                                count += 1
                        return count
                    total_leaf_prompts += count_leaves(module_data)

            st.metric("Total Prompts", total_leaf_prompts)

    with col3:
        if multilingual:
            st.metric("Available Languages", len(available_langs))
        else:
            # Get example prompt from first module
            if modules:
                example_module = get_module_prompts(modules[0])
                if example_module:
                    def find_example(data: dict):
                        for key, value in data.items():
                            if isinstance(value, dict):
                                result = find_example(value)
                                if result:
                                    return result
                            elif isinstance(value, str):
                                return key, value[:50] + "..." if len(value) > 50 else value
                        return None

                    example = find_example(example_module)
                    if example:
                        st.metric("Example Prompt", example[0])
                        st.caption(example[1])





def debug_prompt_manager_state():
    """Debug function to check prompt manager state."""
    from shared.common import get_prompt_manager

    st.subheader("🔍 Prompt Manager Debug State")

    pm = get_prompt_manager()

    col1, col2 = st.columns(2)
    with col1:
        st.write("**Internal State:**")
        st.write(f"- _is_multilingual: {pm._is_multilingual}")
        st.write(f"- _loaded: {pm._loaded}")
        st.write(f"- _available_languages: {pm._available_languages}")
        st.write(f"- _default_language: {pm._default_language}")

    with col2:
        st.write("**Data:**")
        st.write(f"- Multilingual prompts keys: {list(pm._multilingual_prompts.keys()) if pm._multilingual_prompts else 'None'}")
        st.write(f"- Source files count: {len(pm._source_files)}")
        st.write(f"- Legacy prompts empty: {not bool(pm._prompts)}")

    if pm._multilingual_prompts:
        st.write("**Sample French prompt:**")
        try:
            fr_prompt = pm.get_prompt("training.training.system_prompt_default", language="fr")
            st.code(fr_prompt[:200] + "...", language="text")
        except Exception as e:
            st.write(f"Error: {e}")

def inject_ui_admin_tab():
    """Register the Prompt Manager admin tab."""
    return ("Prompts", show_prompt_admin_content)


def inject_ui_initialize():
    """Initialize the prompt manager UI module."""
    return True

# file name: shared/prompt_manager_ui.py
"""
Prompt Manager UI Module

Provides admin interface for viewing and managing all prompts across modules.
"""

import streamlit as st
import yaml
from shared.common import _, log, get_prompt, get_all_prompts, get_module_prompts, list_modules_with_prompts


def format_prompt_for_display(prompt_value, prompt_path="", max_height=400):
    """Format a prompt value for display in Streamlit."""
    # Create a unique key based on the path
    key = f"prompt_display_{prompt_path.replace('.', '_')}"

    if isinstance(prompt_value, str):
        # For strings, show in a text area
        height = min(max_height, max(100, len(prompt_value) // 4))
        return st.text_area(
            "Prompt Content:",
            value=prompt_value,
            height=height,
            key=key,
            disabled=True
        )
    elif isinstance(prompt_value, dict):
        # For dicts, display as YAML
        yaml_str = yaml.dump(prompt_value, default_flow_style=False, allow_unicode=True, indent=2)
        return st.code(yaml_str, language="yaml")
    elif isinstance(prompt_value, list):
        # For lists, show as bullet points
        for i, item in enumerate(prompt_value):
            st.markdown(f"- {item}")
        return None
    else:
        # For other types, just display
        return st.write(prompt_value, key=key)


def show_prompt_admin_content():
    """Display the Prompt Manager admin content."""
    st.title("📝 Prompt Manager")
    st.caption("View all prompts organized by module")

    # Load all prompts
    all_prompts = get_all_prompts()
    modules = list_modules_with_prompts()

    if not modules:
        st.info("No prompts found. Make sure modules have prompts.yaml files.")
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
        module_prompts = get_module_prompts(selected_module)

        if not module_prompts:
            st.info(f"No prompts found for module '{selected_module}'.")
            return

        # Display module info
        st.header(f"Module: {selected_module}")

        # Create tabs for different views
        tab1, tab2, tab3 = st.tabs(["📄 Tree View", "📋 List View", "📊 Statistics"])

        with tab1:
            # Tree view (expandable sections)
            st.subheader("Prompt Tree View")

            def display_prompt_tree(data: dict, path: str = "", depth: int = 0):
                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key
                    indent = "&nbsp;" * (depth * 4)  # HTML indentation

                    if isinstance(value, dict):
                        # Create expander for nested dicts
                        with st.expander(f"{indent}📁 **{key}**", expanded=depth < 2):
                            display_prompt_tree(value, current_path, depth + 1)
                    else:
                        # Display leaf node (actual prompt)
                        st.markdown(f"{indent}**{key}**")
                        format_prompt_for_display(value, 'tree_'+key)  # Pass the path here
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

            for key in sorted(flat_prompts.keys()):
                with st.expander(f"🔑 `{key}`", expanded=False):
                    st.code(key, language="text")
                    format_prompt_for_display(flat_prompts[key], 'list_'+key)  # Pass the key here

        with tab3:
            # Statistics
            st.subheader("Module Statistics")

            def count_prompts(data: dict) -> tuple[int, int]:
                """Count leaf nodes and total nodes."""
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
                    count / leaf_count if leaf_count > 0 else 0,
                    text=f"{type_name}: {count} prompts"
                )

        # Export section
        st.header("Export Options")

        col1, col2 = st.columns(2)

        with col1:
            if st.button("📥 Export as YAML", width='stretch'):
                yaml_data = yaml.dump(
                    module_prompts,
                    default_flow_style=False,
                    allow_unicode=True,
                    indent=2,
                    sort_keys=True
                )

                st.download_button(
                    label="Download YAML File",
                    data=yaml_data,
                    file_name=f"{selected_module}_prompts.yaml",
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
        st.metric("Total Modules", len(modules))

    with col2:
        # Count total leaf prompts across all modules
        total_leaf_prompts = 0
        for module in modules:
            module_data = get_module_prompts(module)

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
        # Get example prompt from first module
        if modules:
            example_module = get_module_prompts(modules[0])

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


def inject_ui_admin_tab():
    """Register the Prompt Manager admin tab."""
    return ("Prompts", show_prompt_admin_content)


def inject_ui_initialize():
    """Initialize the prompt manager UI module."""
    # Nothing special to initialize
    return True

if __name__ == "__main__":
    test_prompt_manager_ui()

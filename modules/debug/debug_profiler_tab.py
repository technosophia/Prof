"""
Debug Profiler Tab
==================

Provides profiling tools to identify performance bottlenecks in the application.
Allows starting/stopping the profiler and viewing filtered results showing only
application code (modules/, shared/, st_shared/).
"""

import cProfile
import io
import pstats
import time
from pstats import SortKey
from typing import List, Optional
import streamlit as st
import os
import tempfile


class AppProfiler:
    """Simple profiler for Streamlit applications."""

    def __init__(self):
        self.profiler: Optional[cProfile.Profile] = None
        self.profile_file: Optional[str] = None
        self.start_time: Optional[float] = None
        self._keep_file = False  # Flag to prevent premature deletion

    def start(self) -> None:
        """Start profiling."""
        with tempfile.NamedTemporaryFile(suffix='.prof', delete=False) as tmp:
            self.profile_file = tmp.name

        self.profiler = cProfile.Profile()
        self.profiler.enable()
        self.start_time = time.time()
        self._keep_file = False

    def stop(self) -> Optional[str]:
        """Stop profiling and return path to profile file."""
        if not self.profiler or not self.profile_file:
            return None

        self.profiler.disable()
        self.profiler.dump_stats(self.profile_file)
        self._keep_file = True  # Keep file for later analysis
        return self.profile_file

    def get_stats(self, profile_file: str, filters: List[str] = None) -> str:
        """
        Get formatted statistics from profile file.

        Args:
            profile_file: Path to profile file
            filters: List of strings to filter function names

        Returns:
            Formatted statistics string
        """
        if not os.path.exists(profile_file):
            return "Error: Profile file not found. Please run profiling again."

        stream = io.StringIO()
        stats = pstats.Stats(profile_file, stream=stream)

        # Sort by cumulative time
        stats.sort_stats(SortKey.CUMULATIVE)

        # Print all stats
        stats.print_stats()

        full_output = stream.getvalue()
        stream.close()

        # If no filters, return everything
        if not filters:
            return full_output

        # Filter lines to show only our code
        filtered_lines = []
        lines = full_output.split('\n')

        # Keep header lines
        header_lines = []
        in_header = True
        for line in lines:
            if in_header:
                filtered_lines.append(line)
                if 'ncalls' in line and 'tottime' in line:
                    in_header = False
            else:
                # Check if line contains any of our filters
                if any(f in line for f in filters):
                    filtered_lines.append(line)

        return '\n'.join(filtered_lines)

    def get_top_functions(self, profile_file: str, filters: List[str] = None, top_n: int = 30) -> str:
        """
        Get top N functions by cumulative time.

        Args:
            profile_file: Path to profile file
            filters: List of strings to filter function names
            top_n: Number of top functions to show

        Returns:
            Formatted statistics string with top functions
        """
        if not os.path.exists(profile_file):
            return "Error: Profile file not found. Please run profiling again."

        stream = io.StringIO()
        stats = pstats.Stats(profile_file, stream=stream)
        stats.sort_stats(SortKey.CUMULATIVE)

        # Print only top N
        stats.print_stats(top_n)

        output = stream.getvalue()
        stream.close()

        # Filter if needed
        if filters:
            filtered_lines = []
            lines = output.split('\n')

            in_header = True
            for line in lines:
                if in_header:
                    filtered_lines.append(line)
                    if 'ncalls' in line and 'tottime' in line:
                        in_header = False
                else:
                    if any(f in line for f in filters):
                        filtered_lines.append(line)

            # Count how many functions we kept
            function_count = sum(1 for line in filtered_lines if ':' in line and '(' in line and ')' in line)

            result = '\n'.join(filtered_lines)
            # Add note about filtering
            if function_count < top_n:
                result = f"📊 Showing {function_count} functions matching filters\n" + result
            return result

        return output

    def cleanup(self, profile_file: str = None):
        """Clean up profile file."""
        file_to_delete = profile_file or self.profile_file
        if file_to_delete and os.path.exists(file_to_delete) and not self._keep_file:
            try:
                os.unlink(file_to_delete)
            except:
                pass


def get_app_source_folders() -> List[str]:
    """Get list of application source folders to filter by."""
    return ['modules/', 'shared/', 'st_shared/', 'core/']


def get_session_state_size():
    """Calculate approximate size of session state."""
    import sys
    total_size = 0
    key_count = 0

    for key, value in st.session_state.items():
        if not key.startswith('_'):
            try:
                total_size += sys.getsizeof(value)
                key_count += 1
            except:
                pass

    return total_size, key_count


def show_profiler_tab():
    """Main profiler tab UI."""
    st.header("⏱️ Performance Profiler")

    # Initialize session state
    if 'profiler_instance' not in st.session_state:
        st.session_state.profiler_instance = AppProfiler()
    if 'profiling_active' not in st.session_state:
        st.session_state.profiling_active = False
    if 'profile_result' not in st.session_state:
        st.session_state.profile_result = None
    if 'profile_duration' not in st.session_state:
        st.session_state.profile_duration = None
    if 'last_profile_file' not in st.session_state:
        st.session_state.last_profile_file = None

    profiler = st.session_state.profiler_instance

    # Control buttons
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        if not st.session_state.profiling_active:
            if st.button("▶️ Start Profiling", type="primary", width='stretch'):
                profiler.start()
                st.session_state.profiling_active = True
                st.session_state.profile_result = None
                st.session_state.last_profile_file = None
                st.rerun()

    with col2:
        if st.session_state.profiling_active:
            if st.button("⏹️ Stop Profiling", type="secondary", width='stretch'):
                profile_file = profiler.stop()
                if profile_file:
                    st.session_state.profiling_active = False
                    st.session_state.last_profile_file = profile_file
                    st.session_state.profile_result = "ready"  # Mark as ready but don't load yet
                    if profiler.start_time:
                        st.session_state.profile_duration = time.time() - profiler.start_time
                st.rerun()

    # Status indicator
    if st.session_state.profiling_active:
        st.info("🔴 Profiling in progress... Click 'Stop Profiling' to see results.")
        if profiler.start_time:
            elapsed = time.time() - profiler.start_time
            st.metric("Current duration", f"{elapsed:.2f}s")

    # Results section
    if st.session_state.last_profile_file and os.path.exists(st.session_state.last_profile_file):
        st.success(f"✅ Profiling completed in {st.session_state.profile_duration:.2f}s")

        # Filter options
        st.subheader("🔍 Filter Options")

        # Get source folders
        source_folders = get_app_source_folders()

        # Multi-select for filters
        selected_filters = st.multiselect(
            "Show only functions from these folders:",
            options=source_folders,
            default=source_folders,
            help="Select which source folders to include in the results"
        )

        # Additional filter input
        custom_filter = st.text_input(
            "Additional filter (e.g., function name or module):",
            placeholder="Enter text to filter functions...",
            help="Show only functions containing this text"
        )

        # Combine filters
        filters = selected_filters.copy()
        if custom_filter:
            filters.append(custom_filter)

        # Display mode
        display_mode = st.radio(
            "Display mode:",
            options=["Top 30 Functions", "Full Statistics"],
            horizontal=True
        )

        # Generate stats
        profile_file = st.session_state.last_profile_file

        if display_mode == "Top 30 Functions":
            if filters:
                result = profiler.get_top_functions(profile_file, filters, top_n=30)
            else:
                result = profiler.get_top_functions(profile_file, top_n=30)
        else:
            if filters:
                result = profiler.get_stats(profile_file, filters)
            else:
                result = profiler.get_stats(profile_file)

        # Display results
        st.subheader("📊 Profile Results")

        # Show filter summary
        if filters:
            st.caption(f"Showing functions matching: {', '.join(filters)}")

        # Results in expander with copy button
        with st.expander("View Profile Data", expanded=True):
            st.code(result, language="")

            # Download button
            st.download_button(
                label="📥 Download Profile Data",
                data=result,
                file_name=f"profile_{int(time.time())}.txt",
                mime="text/plain"
            )

        # Clear button
        if st.button("🔄 Clear Results", width='stretch'):
            # Clean up file
            if os.path.exists(profile_file):
                try:
                    os.unlink(profile_file)
                except:
                    pass
            st.session_state.last_profile_file = None
            st.session_state.profile_result = None
            st.session_state.profile_duration = None
            st.rerun()

    # Quick test section
    with st.expander("🧪 Quick Performance Tests", expanded=False):
        st.markdown("""
        **Common performance issues to check:**
        - Functions with many database calls
        - Large data processing in render functions
        - Missing `@st.cache_data` decorators
        - Excessive session state operations
        - Slow external API calls
        """)

        col_test1, col_test2 = st.columns(2)

        with col_test1:
            if st.button("Test Database Query Performance", width='stretch'):
                try:
                    from st_shared.cached import get_user_manager
                    start = time.time()
                    count = get_user_manager().get_user_count()
                    elapsed = time.time() - start
                    st.success(f"✅ User count query: {count} users in {elapsed:.3f}s")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

        with col_test2:
            if st.button("Test Session State Size", width='stretch'):
                try:
                    size, count = get_session_state_size()
                    st.info(f"📊 Session state: ~{size/1024:.1f} KB ({count} keys)")

                    # Show largest keys
                    if size > 100 * 1024:  # > 100KB
                        st.warning("⚠️ Large session state detected. Consider cleaning up unused keys.")
                except Exception as e:
                    st.error(f"❌ Error: {e}")


def inject_ui_debug_profiler():
    """Injection point for the profiler tab."""
    return show_profiler_tab

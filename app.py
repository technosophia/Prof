import streamlit as st
import os
import sys
import asyncio
from dotenv import load_dotenv

# Load environment variables FIRST
load_dotenv()

# Add shared directory to path
sys.path.append(os.path.join(os.path.dirname(__file__), "shared"))

# Import everything needed - CONFIG FIRST!
from shared.translate import init_translations_streamlit, _streamlit as _
from shared.config import init_config, get_config

# Initialize configuration (one line) - BEFORE ANY OTHER IMPORTS THAT USE CONFIG
config = init_config("config.json")

from shared.logging import log, configure_logging_from_dict
# IMPORTANT: Don't alias 'llm' to avoid name conflicts
from shared.llm import llm_generate, set_current_llm, get_available_llms, get_current_llm_info

# Import user management
from shared.users import user_manager
from shared.database import init_database

# Configure logging from config (one line)
configure_logging_from_dict(config.get("logging", {}))

# Initialize database
db_path = os.path.join("data", "app.db") if os.path.exists("data") else None
init_database(use_memory=False, db_path=db_path, create_default_users=True)

# Initialize translator with Streamlit session support
translator = init_translations_streamlit("en", "translations")

# Page configuration
st.set_page_config(
    page_title="Multilingual App",
    page_icon="🌍",
    layout="centered"
)

def main():
    # Log main function entry
    log("debug", "Entering main function")

    # Get config inside main function
    current_config = get_config()

    # Initialize session state for LLM response
    if "llm_response" not in st.session_state:
        st.session_state.llm_response = ""
    if "streaming_active" not in st.session_state:
        st.session_state.streaming_active = False
    if "stream_buffer" not in st.session_state:
        st.session_state.stream_buffer = ""

    # Initialize session state for user management
    if "current_user" not in st.session_state:
        st.session_state.current_user = None
    if "show_user_form" not in st.session_state:
        st.session_state.show_user_form = False
    if "edit_user_id" not in st.session_state:
        st.session_state.edit_user_id = None

    # Sidebar for language, LLM, and User management
    with st.sidebar:
        st.title("🌍 " + _("language_select"))

        # Show available languages
        available_langs = list(translator.translations.keys())

        # Log available languages
        log("debug", f"Available languages: {available_langs}")

        # Language selector
        lang_option = st.selectbox(
            _("language_select"),
            options=available_langs,
            format_func=lambda x: "English" if x == "en" else "Français",
            index=0 if st.session_state.current_language == "en" else 1,
            key="language_selector"
        )

        # Check if language changed
        if lang_option != st.session_state.current_language:
            old_lang = st.session_state.current_language
            st.session_state.current_language = lang_option
            translator.set_language(lang_option)
            log("info", f"Language changed from '{old_lang}' to '{lang_option}'")
            st.rerun()

        st.divider()

        # User Management Section
        st.title("👤 User Management")

        # Current user info
        if st.session_state.current_user:
            st.info(f"**Current User:** {st.session_state.current_user['name']}")
            if st.button("Switch User"):
                st.session_state.current_user = None
                st.rerun()
        else:
            st.warning("No user selected")

            # User selector - USING get_all_users_dict() instead of get_all_users()
            all_users = user_manager.get_all_users_dict()  # CHANGÉ ICI
            if all_users:
                user_options = ["Select a user..."] + list(all_users.keys())
                user_display = ["Select a user..."] + [f"{user['name']} ({user_id})" for user_id, user in all_users.items()]  # CHANGÉ ICI

                selected_user = st.selectbox(
                    "Choose user",
                    options=user_options,
                    format_func=lambda x: user_display[user_options.index(x)] if x in user_options else x,
                    key="user_selector"
                )

                if selected_user != "Select a user..." and selected_user:
                    if st.button("Login as User"):
                        st.session_state.current_user = all_users[selected_user]
                        log("info", f"User logged in: {st.session_state.current_user['name']}")
                        st.rerun()

        # Create new user button
        if st.button("➕ Create New User", type="primary"):
            st.session_state.show_user_form = True
            st.session_state.edit_user_id = None

        st.divider()

        # LLM Selection
        st.title("🤖 " + _("llm_selection"))

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
            if current_llm_info:
                try:
                    current_index = llm_options.index(current_llm_info["id"])
                except ValueError:
                    current_index = 0

            selected_llm_id = st.selectbox(
                _("select_llm"),
                options=llm_options,
                format_func=lambda x: llm_display_names[llm_options.index(x)],
                index=current_index,
                key="llm_selector"
            )

            # Check if LLM changed
            if selected_llm_id != (current_llm_info.get("id") if current_llm_info else None):
                if set_current_llm(selected_llm_id):
                    log("info", f"LLM changed to: {selected_llm_id}")
                    st.rerun()
                else:
                    st.error(f"Failed to switch to LLM: {selected_llm_id}")

        st.divider()
        st.caption(_("current_language"))

        # Show current LLM info in sidebar
        if current_llm_info:
            st.info(f"**Current LLM:** {current_llm_info['name']}")
            st.caption(f"Type: {current_llm_info['type']}")
            st.caption(f"Model: {current_llm_info['model']}")
            st.caption(f"Status: {'✅ Available' if current_llm_info['available'] else '❌ Unavailable'}")

    # Main content
    st.title(_("hello_world"))
    st.write(_("description"))

    # Show current user info if logged in
    if st.session_state.current_user:
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            st.success(f"✅ Logged in as: **{st.session_state.current_user['name']}**")
        with col2:
            if st.button("👤 Profile"):
                st.session_state.edit_user_id = st.session_state.current_user['id']
                st.session_state.show_user_form = True
        with col3:
            if st.button("🚪 Logout"):
                st.session_state.current_user = None
                st.rerun()

    # Log that we're displaying main content
    log("debug", "Displaying main content")

    # User Management Form (shown when creating/editing users)
    if st.session_state.show_user_form:
        st.divider()
        st.subheader("👤 " + ("Edit User" if st.session_state.edit_user_id else "Create New User"))

        with st.form("user_form"):
            if st.session_state.edit_user_id:
                # Editing existing user
                user = user_manager.get_user(st.session_state.edit_user_id)
                default_name = user["name"] if user else ""
                default_email = user["email"] if user else ""
            else:
                # Creating new user
                default_name = ""
                default_email = ""

            name = st.text_input("Name *", value=default_name)
            email = st.text_input("Email", value=default_email)

            col1, col2 = st.columns(2)
            with col1:
                submit = st.form_submit_button("💾 Save User", type="primary")
            with col2:
                cancel = st.form_submit_button("❌ Cancel")

            if submit:
                if not name.strip():
                    st.error("Name is required")
                else:
                    try:
                        if st.session_state.edit_user_id:
                            # Update existing user
                            success = user_manager.update_user(
                                st.session_state.edit_user_id,
                                name=name.strip(),
                                email=email.strip() if email else None
                            )
                            if success:
                                st.success("User updated successfully!")
                                # Update current user if editing self
                                if (st.session_state.current_user and
                                    st.session_state.current_user['id'] == st.session_state.edit_user_id):
                                    st.session_state.current_user = user_manager.get_user(st.session_state.edit_user_id)
                                log("info", f"User updated: {name}")
                            else:
                                st.error("Failed to update user")
                        else:
                            # Create new user
                            user_id = user_manager.create_user(
                                name=name.strip(),
                                email=email.strip() if email else None
                            )
                            st.success(f"User created successfully! ID: {user_id}")
                            log("info", f"User created: {name} (ID: {user_id})")

                        # Reset form state
                        st.session_state.show_user_form = False
                        st.session_state.edit_user_id = None
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
                        log("error", f"User form error: {str(e)}")

            if cancel:
                st.session_state.show_user_form = False
                st.session_state.edit_user_id = None
                st.rerun()

    # User List (only show if not showing form)
    elif not st.session_state.show_user_form:
        st.divider()
        st.subheader("👥 All Users")

        # Get all users - USING get_all_users() which returns a list
        all_users_list = user_manager.get_all_users()  # CHANGÉ ICI

        if all_users_list:
            # Create a table of users
            user_data = []
            for user in all_users_list:  # CHANGÉ ICI
                user_data.append({
                    "ID": user["id"],
                    "Name": user["name"],
                    "Email": user["email"] or "-",
                    "Created": user["created_at"][:10] if user["created_at"] else "-",
                    "Status": "✅ Active" if user.get("is_active", True) else "❌ Inactive",
                    "Actions": user["id"]
                })

            # Display users in columns
            for user_row in user_data:
                col1, col2, col3, col4, col5, col6 = st.columns([1, 3, 3, 2, 2, 2])
                with col1:
                    st.write(user_row["ID"][:8] + "...")
                with col2:
                    st.write(user_row["Name"])
                with col3:
                    st.write(user_row["Email"])
                with col4:
                    st.write(user_row["Created"])
                with col5:
                    st.write(user_row["Status"])
                with col6:
                    col_a, col_b = st.columns(2)
                    with col_a:
                        if st.button("✏️", key=f"edit_{user_row['Actions']}", help="Edit user"):
                            st.session_state.edit_user_id = user_row["Actions"]
                            st.session_state.show_user_form = True
                            st.rerun()
                    with col_b:
                        if st.button("🗑️", key=f"delete_{user_row['Actions']}", help="Delete user"):
                            if user_manager.delete_user(user_row["Actions"]):
                                st.success(f"User {user_row['Name']} deleted")
                                if (st.session_state.current_user and
                                    st.session_state.current_user['id'] == user_row["Actions"]):
                                    st.session_state.current_user = None
                                st.rerun()
                            else:
                                st.error("Cannot delete default test users")
        else:
            st.info("No users found. Create your first user!")

        st.divider()

    # Example button with logging
    if st.button(_("button_text"), type="primary"):
        log("info", "Main button clicked")
        st.success(_("button_clicked"))

    # LLM Chat Section (only show if a user is logged in)
    if st.session_state.current_user:
        st.divider()
        st.subheader("🤖 " + _("llm_chat"))

        # Text area for user input
        user_message = st.text_area(
            _("enter_message"),
            value=_("default_prompt"),
            height=150,
            key="user_message"
        )

        # Columns for buttons
        col1, col2 = st.columns(2)

        with col1:
            # Send button
            if st.button("🚀 " + _("send_message"), type="primary", use_container_width=True):
                if user_message.strip():
                    log("info", f"Sending message to LLM: {user_message[:50]}...")

                    # Clear previous response
                    st.session_state.llm_response = ""
                    st.session_state.stream_buffer = ""
                    st.session_state.streaming_active = True

                    # Create a placeholder for the streaming response
                    response_placeholder = st.empty()

                    # Define streaming callback
                    def stream_callback(chunk):
                        st.session_state.stream_buffer += chunk
                        response_placeholder.markdown(st.session_state.stream_buffer)

                    # Run async LLM call
                    try:
                        # Use llm_generate directly instead of aliased 'llm'
                        response = asyncio.run(llm_generate(user_message.strip(), stream_callback))
                        st.session_state.llm_response = response
                        st.session_state.streaming_active = False

                        # If streaming didn't work, show the full response
                        if not st.session_state.stream_buffer and response:
                            st.markdown(response)

                        log("info", "LLM response received")
                    except Exception as e:
                        error_msg = f"Error calling LLM: {str(e)}"
                        log("error", error_msg, exc_info=True)  # Use exc_info=True for traceback
                        st.error(error_msg)
                else:
                    st.warning(_("please_enter_message"))

        with col2:
            # Clear button
            if st.button("🗑️ " + _("clear_chat"), use_container_width=True):
                st.session_state.llm_response = ""
                st.session_state.stream_buffer = ""
                st.session_state.streaming_active = False
                log("info", "Chat cleared")
                st.rerun()

        # Display the response if we have one
        if st.session_state.llm_response and not st.session_state.streaming_active:
            st.divider()
            st.subheader("💬 " + _("response"))
            st.markdown(st.session_state.llm_response)

        # Display streaming buffer if active
        elif st.session_state.streaming_active and st.session_state.stream_buffer:
            st.divider()
            st.subheader("💬 " + _("response_streaming"))
            st.markdown(st.session_state.stream_buffer)
            st.caption("⏳ " + _("streaming_in_progress"))
    else:
        # Show message when no user is logged in
        st.divider()
        st.warning("👤 Please select or create a user from the sidebar to use the LLM chat feature.")

    # Debug section in sidebar expander
    with st.expander("🔧 " + _("debug_info")):
        st.write(f"**Current language:** {translator.get_current_language()}")
        st.write(f"**Available languages:** {', '.join(available_langs)}")
        st.write(f"**Log level from config:** {current_config.get('logging.level', 'INFO')}")
        st.write(f"**App name:** {current_config.get('app.name')}")
        st.write(f"**App version:** {current_config.get('app.version')}")

        # User info
        st.write("**User Info:**")
        if st.session_state.current_user:
            st.write(f"- Current User: {st.session_state.current_user['name']} ({st.session_state.current_user['id']})")
            st.write(f"- Email: {st.session_state.current_user['email']}")
            st.write(f"- Created: {st.session_state.current_user['created_at']}")
            st.write(f"- Active: {st.session_state.current_user['is_active']}")
        else:
            st.write("- No user logged in")

        st.write(f"**Total Users:** {user_manager.get_user_count()}")

        # Current LLM info
        if current_llm_info:
            st.write("**Current LLM:**")
            st.write(f"- ID: {current_llm_info['id']}")
            st.write(f"- Name: {current_llm_info['name']}")
            st.write(f"- Type: {current_llm_info['type']}")
            st.write(f"- Model: {current_llm_info['model']}")
            st.write(f"- Available: {current_llm_info['available']}")

        # All LLMs info
        st.write("**All LLMs:**")
        for llm_item in available_llms_list:
            status = "🟢" if llm_item["available"] else "🔴"
            st.write(f"- {status} {llm_item['name']} ({llm_item['type']}): {llm_item['description']}")

        # Environment info
        st.write("**Environment Info:**")
        st.write(f"- GEMINI_API_KEY present: {'Yes' if os.getenv('GEMINI_API_KEY') else 'No'}")
        st.write(f"- GROQ_API_KEY present: {'Yes' if os.getenv('GROQ_API_KEY') else 'No'}")
        st.write(f"- OLLAMA_BASE_URL: {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")

        # Database info
        st.write("**Database Info:**")
        st.write(f"- Database path: {db_path}")
        st.write(f"- Data directory exists: {os.path.exists('data')}")

        # Test logging buttons
        st.subheader("Test Logging")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("Debug", key="debug_btn"):
                log("debug", "Debug test message from Streamlit")
                st.success("Debug message logged")
        with col2:
            if st.button("Info", key="info_btn"):
                log("info", "Info test message from Streamlit")
                st.success("Info message logged")
        with col3:
            if st.button("Warning", key="warning_btn"):
                log("warning", "Warning test message from Streamlit")
                st.success("Warning message logged")
        with col4:
            if st.button("Error", key="error_btn"):
                log("error", "Error test message from Streamlit", exc_info=False)
                st.success("Error message logged")

        # Test error with traceback
        if st.button("Test Error with Traceback"):
            try:
                # Create a test error
                raise ValueError("This is a test error for traceback")
            except Exception as e:
                log("error", "Test error with traceback", exc_info=True)
                st.success("Error with traceback logged")

if __name__ == "__main__":
    main()

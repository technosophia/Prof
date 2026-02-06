import streamlit as st
from test_component import test_component

# Initialize session state
if 'result' not in st.session_state:
    st.session_state.result = None
if 'clicked' not in st.session_state:
    st.session_state.clicked = False
if 'user_input' not in st.session_state:
    st.session_state.user_input = "demo"

# App UI
st.title("Minimal Component Test")

# Display current session state
st.write(f"**Current session state value:** `{st.session_state.user_input}`")

# User input field with callback to update session state
def update_user_input():
    st.session_state.user_input = st.session_state.widget_user_input
    st.write(f"**[DEBUG] Input updated to:** `{st.session_state.user_input}`")

# Create text input with separate widget key
user_input = st.text_input(
    "Enter text to send to component:",
    value=st.session_state.user_input,
    key="widget_user_input",
    on_change=update_user_input
)

# Single test button
if st.button("Test", type="primary"):
    st.session_state.clicked = True
    st.write(f"**[DEBUG] Button clicked, sending:** `{st.session_state.user_input}`")
else:
    st.session_state.clicked = False

# Call component
st.write("**Component Output:**")
result = test_component(
    input_value=st.session_state.user_input,
    button_clicked=st.session_state.clicked,
    key="test_component_key"  # Changed key for clarity
)

# Store and display result
if result is not None:
    st.session_state.result = result
    st.success(f"**Result:** {st.session_state.result}")
else:
    st.info("Enter text above and click 'Test' to start communication")

# Debug section
with st.expander("Debug Info"):
    st.write(f"Session State: {dict(st.session_state)}")
    st.write(f"Component returned: {result}")

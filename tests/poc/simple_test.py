import streamlit as st
from test_component import test_component

# Session state
if 'result' not in st.session_state:
    st.session_state.result = None
if 'clicked' not in st.session_state:
    st.session_state.clicked = False

# App UI
st.title("Minimal Component Test")

# Display prefilled value
prefilled = "demo"
st.write(f"**Prefilled value:** `{prefilled}`")

# Single test button
if st.button("Test"):
    st.session_state.clicked = True
    print("[PYTHON] Button clicked, sending to component")
else:
    st.session_state.clicked = False

# Call component
result = test_component(
    input_value=prefilled,
    button_clicked=st.session_state.clicked,
    key="test"
)

# Store and display result
if result is not None:
    st.session_state.result = result
    print(f"[PYTHON] Received from JS: {result}")

# Display result
if st.session_state.result:
    st.success(f"Result: {st.session_state.result}")
else:
    st.info("Click 'Test' to start communication")

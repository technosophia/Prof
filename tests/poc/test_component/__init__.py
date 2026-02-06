import os
import streamlit.components.v1 as components

# Declare component with path to pre-built HTML
_COMPONENT_PATH = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_PATH = os.path.join(_COMPONENT_PATH, "frontend")

# Simple component declaration
test_component = components.declare_component(
    "test_component",
    path=_FRONTEND_PATH
)

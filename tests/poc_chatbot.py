import streamlit as st
import streamlit.components.v1 as components
import json
from datetime import datetime
import time

# Page config
st.set_page_config(page_title="Secure LLM Chat", page_icon="🔒", layout="wide")

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "logs" not in st.session_state:
    st.session_state.logs = []
if "waiting_for_response" not in st.session_state:
    st.session_state.waiting_for_response = False
if "response_trigger" not in st.session_state:
    st.session_state.response_trigger = 0

def log(message, level="INFO"):
    """Add a log message with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_entry = f"[{timestamp}] [{level}] {message}"
    st.session_state.logs.append(log_entry)
    print(log_entry)

# Title
st.title("🔒 Secure LLM Chat")
st.caption("Your API key never leaves your browser")

# Sidebar for configuration and logs
with st.sidebar:
    st.header("Configuration")
    st.info("These settings are stored in your browser only")

    if st.button("🗑️ Clear Chat History"):
        log("Clearing chat history", "INFO")
        st.session_state.messages = []
        st.rerun()

    if st.button("🧹 Clear Logs"):
        st.session_state.logs = []
        st.rerun()

    st.markdown("---")
    st.subheader("📋 Debug Logs")
    if st.session_state.logs:
        for log_entry in st.session_state.logs[-20:]:
            st.text(log_entry)
    else:
        st.text("No logs yet...")

# Main component - handles both config and LLM communication
def create_llm_component(messages_to_send=None):
    """
    Create the LLM component that handles configuration and API calls
    If messages_to_send is provided, it will make an API call
    """
    log(f"Creating LLM component (sending: {messages_to_send is not None})", "INFO")

    # Prepare the messages JSON
    messages_json = json.dumps(messages_to_send) if messages_to_send else "null"

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {{ margin: 0; padding: 20px; font-family: sans-serif; }}
            .config-section {{ margin-bottom: 20px; padding: 15px; background: #f0f2f6; border-radius: 5px; }}
            .config-section label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            .config-section input {{ width: 100%; padding: 8px; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }}
            .config-section button {{ padding: 8px 16px; background: #ff4b4b; color: white; border: none; border-radius: 4px; cursor: pointer; }}
            .config-section button:hover {{ background: #ff3333; }}
            .status {{ padding: 10px; margin-top: 10px; border-radius: 4px; }}
            .status.success {{ background: #d4edda; color: #155724; }}
            .status.error {{ background: #f8d7da; color: #721c24; }}
            .status.info {{ background: #d1ecf1; color: #0c5460; }}
        </style>
    </head>
    <body>
        <div class="config-section">
            <label>API Base URL:</label>
            <input type="text" id="apiUrl" placeholder="https://api.groq.com/openai/v1" />

            <label>API Key:</label>
            <input type="password" id="apiKey" placeholder="Enter your API key" />

            <label>Model:</label>
            <input type="text" id="model" placeholder="llama-3.3-70b-versatile" />

            <button onclick="saveConfig()">💾 Save Configuration</button>
            <div id="status"></div>
        </div>

        <script>
            function jsLog(message, level = 'INFO') {{
                const timestamp = new Date().toISOString().split('T')[1].slice(0, -1);
                console.log(`[JS ${{timestamp}}] [${{level}}] ${{message}}`);
            }}

            jsLog('Component loaded');

            // Load configuration from localStorage
            function loadConfig() {{
                const apiUrl = localStorage.getItem('llm_api_url') || '';
                const apiKey = localStorage.getItem('llm_api_key') || '';
                const model = localStorage.getItem('llm_model') || '';

                document.getElementById('apiUrl').value = apiUrl;
                document.getElementById('apiKey').value = apiKey;
                document.getElementById('model').value = model;

                if (apiUrl && apiKey && model) {{
                    jsLog(`Config loaded: URL=${{apiUrl}}, Model=${{model}}`);
                    showStatus('Configuration loaded', 'info');
                }}

                return {{ apiUrl, apiKey, model }};
            }}

            function saveConfig() {{
                jsLog('Saving configuration');
                const apiUrl = document.getElementById('apiUrl').value;
                const apiKey = document.getElementById('apiKey').value;
                const model = document.getElementById('model').value;

                if (!apiUrl || !apiKey || !model) {{
                    showStatus('Please fill in all fields', 'error');
                    return;
                }}

                localStorage.setItem('llm_api_url', apiUrl);
                localStorage.setItem('llm_api_key', apiKey);
                localStorage.setItem('llm_model', model);

                jsLog('Configuration saved');
                showStatus('Configuration saved!', 'success');
            }}

            function showStatus(message, type) {{
                const statusDiv = document.getElementById('status');
                statusDiv.className = 'status ' + type;
                statusDiv.textContent = message;
                setTimeout(() => {{
                    statusDiv.textContent = '';
                    statusDiv.className = 'status';
                }}, 3000);
            }}

            async function sendToLLM(messages) {{
                jsLog('sendToLLM called with ' + messages.length + ' messages');

                const config = loadConfig();
                if (!config.apiUrl || !config.apiKey || !config.model) {{
                    jsLog('Configuration missing', 'ERROR');
                    return {{ error: 'Please configure your API settings first' }};
                }}

                const endpoint = config.apiUrl + '/chat/completions';
                jsLog('Sending request to: ' + endpoint);

                try {{
                    const response = await fetch(endpoint, {{
                        method: 'POST',
                        headers: {{
                            'Content-Type': 'application/json',
                            'Authorization': 'Bearer ' + config.apiKey
                        }},
                        body: JSON.stringify({{
                            model: config.model,
                            messages: messages,
                            stream: false
                        }})
                    }});

                    jsLog('Response status: ' + response.status);

                    if (!response.ok) {{
                        const errorText = await response.text();
                        jsLog('API error: ' + errorText.substring(0, 200), 'ERROR');
                        throw new Error('API error ' + response.status + ': ' + errorText);
                    }}

                    const data = await response.json();
                    const content = data.choices[0].message.content;
                    jsLog('Response received, length: ' + content.length);

                    return {{ content: content }};

                }} catch (error) {{
                    jsLog('Error: ' + error.message, 'ERROR');
                    return {{ error: error.message }};
                }}
            }}

            // Main execution
            (async function() {{
                jsLog('Initializing component');
                loadConfig();

                const messagesToSend = {messages_json};

                if (messagesToSend) {{
                    jsLog('Messages to send detected, calling LLM');
                    const result = await sendToLLM(messagesToSend);
                    jsLog('Got result, sending to Streamlit: ' + JSON.stringify(result).substring(0, 100));

                    // CRITICAL: Use Streamlit.setComponentValue to return data
                    if (window.Streamlit) {{
                        jsLog('Using Streamlit.setComponentValue');
                        window.Streamlit.setComponentValue(result);
                    }} else {{
                        jsLog('Streamlit not available, using postMessage');
                        window.parent.postMessage({{
                            type: 'streamlit:setComponentValue',
                            value: result
                        }}, '*');
                    }}
                }} else {{
                    jsLog('No messages to send, component ready');
                }}
            }})();
        </script>
    </body>
    </html>
    """

    return components.html(html_code, height=300 if messages_to_send is None else 0, scrolling=True)

# Display configuration section
st.subheader("API Configuration")
create_llm_component()

st.markdown("---")

# Chat interface
st.subheader("Chat")

# Display chat messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Check if we're waiting for a response
if st.session_state.waiting_for_response:
    log("Checking for LLM response...", "DEBUG")

    # Create the component again to get the response
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        message_placeholder.markdown("⏳ Waiting for response...")

        # Get API messages
        api_messages = [{"role": m["role"], "content": m["content"]} for m in st.session_state.messages]

        # Call component and check for response
        response = create_llm_component(messages_to_send=api_messages)

        log(f"Response check - type: {type(response)}, value: {response}", "DEBUG")

        if response and isinstance(response, dict):
            log("Got valid response!", "INFO")
            st.session_state.waiting_for_response = False

            if "error" in response:
                log(f"Error: {response['error']}", "ERROR")
                message_placeholder.error(f"❌ Error: {response['error']}")
            elif "content" in response:
                assistant_message = response["content"]
                log(f"Success! Response length: {len(assistant_message)}", "INFO")
                message_placeholder.markdown(assistant_message)
                st.session_state.messages.append({"role": "assistant", "content": assistant_message})
                time.sleep(0.5)  # Small delay to ensure message is added
                st.rerun()
        else:
            log("No response yet, will rerun", "DEBUG")
            # Trigger another rerun to check for response
            time.sleep(0.5)
            st.rerun()

# Chat input
if prompt := st.chat_input("Type your message...", disabled=st.session_state.waiting_for_response):
    log(f"User input: {prompt[:50]}...", "INFO")

    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    log(f"Total messages: {len(st.session_state.messages)}", "INFO")

    # Set waiting flag
    st.session_state.waiting_for_response = True
    log("Set waiting flag, triggering rerun", "INFO")

    # Rerun to start the waiting loop
    st.rerun()

# Instructions
with st.expander("ℹ️ How to use"):
    st.markdown("""
    ### Setup Instructions:

    1. **Configure your API settings** in the form above:
       - **API Base URL**: e.g., `https://api.groq.com/openai/v1`
       - **API Key**: Your personal API key
       - **Model**: e.g., `llama-3.3-70b-versatile`

    2. **Click "Save Configuration"**

    3. **Start chatting!**

    ### Supported Providers:
    - **Groq**: `https://api.groq.com/openai/v1`
    - **OpenAI**: `https://api.openai.com/v1`
    - Any OpenAI-compatible endpoint

    ### Security:
    Your API key is stored **only in your browser** (localStorage) and never sent to the Streamlit server.

    ### Debug:
    - Check sidebar for Python logs
    - Open browser console (F12) for JavaScript logs

    ### How it works:
    When you send a message, the app enters a "waiting" state and keeps re-rendering until the JavaScript
    component returns the LLM response. This typically takes 1-2 seconds.
    """)

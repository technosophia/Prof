import warnings
import logging

def ignore_warnings():
    _SILENCED_WARNINGS = [
        ("ignore", UserWarning,        "streamlit.runtime.scriptrunner_utils"),
        ("ignore", UserWarning,        "streamlit.runtime.state.session_state_proxy"),
        ("ignore", UserWarning,        r"torch\.cuda"),
        ("ignore", DeprecationWarning, None),
    ]
    for action, category, module in _SILENCED_WARNINGS:
        kw = {"category": category}
        if module:
            kw["module"] = module
        warnings.filterwarnings(action, **kw)

    warnings.filterwarnings(
        "ignore",
        message="Thread 'MainThread': missing ScriptRunContext!",
        category=UserWarning,
    )

    # Filter SWIG DeprecationWarnings
    warnings.filterwarnings(
        "ignore",
        message="builtin type SwigPyPacked has no __module__ attribute",
        category=DeprecationWarning,
    )

    warnings.filterwarnings(
        "ignore",
        message="builtin type SwigPyObject has no __module__ attribute",
        category=DeprecationWarning,
    )

    warnings.filterwarnings(
        "ignore",
        message="builtin type swigvarlink has no __module__ attribute",
        category=DeprecationWarning,
    )

    for logger_name in (
        "streamlit",
        "streamlit.runtime",
        "streamlit.runtime.scriptrunner_utils",
        "streamlit.runtime.scriptrunner_utils.script_run_context",
        "streamlit.runtime.state",
        "streamlit.runtime.state.session_state_proxy",
    ):
        _logger = logging.getLogger(logger_name)
        _logger.handlers.clear()
        _logger.propagate = False
        _logger.disabled = True
        _logger.setLevel(logging.CRITICAL)

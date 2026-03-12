from core.logging import log
from shared.common import check_services
from shared.conversation import get_conversation_manager
from modules.llm_monitor.llm_monitor_factory import get_llm_monitor, reset_llm_monitor

_LLM_MANAGER = None
_MONITOR_CALLBACK = None
_CONV_CLEANUP_CALLBACK = None


def on_module_activated(services) -> None:
    global _LLM_MANAGER, _MONITOR_CALLBACK, _CONV_CLEANUP_CALLBACK

    required = check_services(
        ["config", "db_manager", "llm_manager"],
        services=services,
        module_name="llm_monitor",
    )
    config = required["config"]
    db_manager = required["db_manager"]
    llm_manager = required["llm_manager"]

    reset_llm_monitor()
    monitor = get_llm_monitor(config=config, db_manager=db_manager)

    def monitor_callback(monitor_data):
        monitor.log_llm_call(monitor_data)
    monitor_callback.__name__ = "llm_monitor_callback"

    # --- conversation FK cleanup ---
    def cleanup_conversation_llm_calls(conversation_id: str):
        try:
            with db_manager.get_session() as session:
                from modules.llm_monitor.models import LLMCallTable
                session.query(LLMCallTable).filter_by(
                    conversation_id=conversation_id
                ).delete()
        except Exception as e:
            log("error", f"llm_monitor: failed to clean llm_calls "
                         f"for conversation {conversation_id}: {e}")
    cleanup_conversation_llm_calls.__name__ = "cleanup_conversation_llm_calls"

    _LLM_MANAGER = llm_manager
    _MONITOR_CALLBACK = monitor_callback
    _CONV_CLEANUP_CALLBACK = cleanup_conversation_llm_calls

    _LLM_MANAGER.register_monitor_callback(_MONITOR_CALLBACK)
    get_conversation_manager().register_before_delete_callback(
        _CONV_CLEANUP_CALLBACK
    )

    log("info", "llm_monitor: activated")


def on_module_deactivated() -> None:
    global _LLM_MANAGER, _MONITOR_CALLBACK, _CONV_CLEANUP_CALLBACK
    if _LLM_MANAGER is not None and _MONITOR_CALLBACK is not None:
        _LLM_MANAGER.unregister_monitor_callback(_MONITOR_CALLBACK)
    if _CONV_CLEANUP_CALLBACK is not None:
        get_conversation_manager().unregister_before_delete_callback(
            _CONV_CLEANUP_CALLBACK
        )
    _LLM_MANAGER = None
    _MONITOR_CALLBACK = None
    _CONV_CLEANUP_CALLBACK = None
    log("info", "llm_monitor: deactivated")

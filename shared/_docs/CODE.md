<!-- /shared/_docs/CODE.md -->

# Best Practices Quick Reference

1. **Import from common.py only**: Never import directly from core/shared modules
2. **Initialize in order**: Config → Logging → Database → Other systems
3. **Use session state for language**: Translation uses `st.session_state.current_language`
4. **Always use db sessions as context managers**: `with get_db_manager().get_session() as session:`
5. **Log errors with tracebacks**: Use `exc_info=True` for error logs
6. **Test with in-memory database**: Use `init_database(use_memory=True)` in tests
7. **Cleanup test data**: Use `db_manager.empty_all_tables()` between tests
8. **Cache singletons**: All managers in common.py use `@st.cache_resource` for global state

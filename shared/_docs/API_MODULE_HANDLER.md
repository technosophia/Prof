<!-- shared/_docs/API_MODULE_HANDLER.md -->

<!-- GENERATED FILE - do not edit manually -->
<!-- Source: shared/module_handler.py -->

# API — module_handler

---

### `get_active_modules`

```python
def get_active_modules() -> List[str]:
```

Convenience function to get active modules without creating a handler.

### `load_module_ui`

```python
def load_module_ui(module_name: str) -> Optional[object]:
```

Convenience function to load a module's UI component.

### `module_exists`

```python
def module_exists(module_name: str) -> bool:
```

Convenience function to check if a module exists.

### `get_available_modules_count`

```python
def get_available_modules_count() -> int:
```

Convenience function to get the number of available modules.

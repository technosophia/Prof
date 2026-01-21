"""
LLM Manager using plugin-based engine system.
"""

import os
import sys
import importlib
import pkgutil
from typing import Dict, Any, List, Optional, Callable
import asyncio

# Import shared systems
from shared.config import get_config
from shared.logging import log

# Import base engine
from shared.llm_engine import LLMEngine


class LLMManager:
    def __init__(self):
        """Initialize LLM Manager using plugin-based engine system."""
        self.config = get_config()
        self.engines = {}
        self.current_llm = None

        # Discover and load all engine modules
        self.discover_engines()

        # Validate config
        self.validate_config()

        # Initialize current LLM
        self.initialize_current_llm()

        log("debug", f"LLMManager initialized with {len(self.engines)} engines")

    def discover_engines(self):
        """Discover and load all LLM engine modules."""
        # Look for llm_*.py files in the current directory
        import shared.llm_engine as engine_module

        # Get the package path
        package_path = os.path.dirname(engine_module.__file__)

        # Find all llm_*.py files
        for _, module_name, is_pkg in pkgutil.iter_modules([package_path]):
            if module_name.startswith('llm_') and module_name != 'llm_engine':
                try:
                    # Import the module
                    module = importlib.import_module(f"{module_name}")

                    # Find engine classes (classes ending with 'Engine')
                    for attr_name in dir(module):
                        attr = getattr(module, attr_name)
                        if (isinstance(attr, type) and
                            issubclass(attr, LLMEngine) and
                            attr != LLMEngine and
                            attr_name.endswith('Engine')):

                            # Create instance
                            engine = attr()
                            engine_type = engine.engine_type

                            # Add to engines
                            self.engines[engine_type] = engine
                            log("info", f"Loaded LLM engine: {engine_type}")
                            break

                except Exception as e:
                    log("error", f"Failed to load engine module {module_name}: {e}")

        # Log discovered engines
        log("debug", f"Discovered engines: {list(self.engines.keys())}")

    def get_engine(self, engine_type: str) -> Optional[LLMEngine]:
        """Get engine by type."""
        return self.engines.get(engine_type)

    def initialize_current_llm(self):
        """Initialize the current LLM from config."""
        default_llm_name = self.config.get("app.default_llm", "Qwen 3 4B")
        log("debug", f"Looking for default LLM: '{default_llm_name}'")

        available_llms = self.get_available_llms()

        if available_llms:
            log("debug", f"Available LLMs found: {len(available_llms)}")
            for llm in available_llms:
                log("debug", f"  - '{llm['name']}' (ID: '{llm['id']}', Available: {llm['available']})")
        else:
            log("debug", "No LLMs returned from get_available_llms()")

        # First try to find by exact name match
        for llm in available_llms:
            if llm["name"] == default_llm_name:
                if llm["available"]:
                    self.current_llm = llm["id"]
                    log("info", f"Current LLM set to: {default_llm_name} (ID: {self.current_llm})")
                    return
                else:
                    log("warning", f"Default LLM '{default_llm_name}' found but not available")

        # If not found by exact name, try case-insensitive match
        for llm in available_llms:
            if llm["name"].lower() == default_llm_name.lower():
                if llm["available"]:
                    self.current_llm = llm["id"]
                    log("info", f"Current LLM set to: {llm['name']} (ID: {self.current_llm})")
                    return
                else:
                    log("warning", f"Default LLM '{llm['name']}' found (case-insensitive) but not available")

        # If not found by name, try by ID (in case default_llm is actually an ID)
        for llm in available_llms:
            if llm["id"] == default_llm_name:
                if llm["available"]:
                    self.current_llm = llm["id"]
                    log("info", f"Current LLM set by ID: {default_llm_name}")
                    return
                else:
                    log("warning", f"Default LLM ID '{default_llm_name}' found but not available")

        # Fallback to first available LLM
        for llm in available_llms:
            if llm["available"]:
                self.current_llm = llm["id"]
                log("warning", f"No default LLM '{default_llm_name}' found, falling back to: {llm['name']}")
                return

        if available_llms:
            log("error", f"No available LLMs found among {len(available_llms)} configured LLMs")
            # At least set the first one even if not available
            self.current_llm = available_llms[0]["id"]
            log("warning", f"Forcing current LLM to first configured: {available_llms[0]['name']}")
        else:
            log("error", "No LLMs configured at all")
            self.current_llm = None

    def get_available_llms(self) -> List[Dict[str, Any]]:
        """Get list of available LLMs from configuration."""
        llms = []

        if "llms" not in self.config:
            log("error", "No 'llms' section found in configuration")
            return llms

        for llm_id, llm_config in self.config.get("llms", {}).items():
            if not isinstance(llm_config, dict):
                log("warning", f"Invalid LLM config for '{llm_id}': {llm_config}")
                continue

            enabled = llm_config.get("enabled", True)
            llm_type = llm_config.get("type", "unknown")

            # Check if engine exists
            engine = self.get_engine(llm_type)

            # Check availability
            is_available = False
            if enabled and engine:
                if llm_config.get("requires_api_key", False):
                    is_available = engine.is_available()
                else:
                    is_available = True

            llms.append({
                "id": llm_id,
                "name": llm_config.get("name", llm_id),
                "type": llm_type,
                "model": llm_config.get("model", "unknown"),
                "description": llm_config.get("description", ""),
                "enabled": enabled,
                "available": is_available,
                "requires_api_key": llm_config.get("requires_api_key", False),
                "engine": engine
            })

        # Log availability summary
        total = len(llms)
        available_count = sum(1 for llm in llms if llm["available"])
        enabled_count = sum(1 for llm in llms if llm["enabled"])

        log("debug", f"LLM Status: {available_count}/{total} available, {enabled_count}/{total} enabled")

        return llms

    def set_current_llm(self, llm_id: str) -> bool:
        """Set the current LLM to use."""
        available_llms = self.get_available_llms()

        log("debug", f"Attempting to set LLM to: {llm_id}")

        for llm in available_llms:
            if llm["id"] == llm_id:
                if llm["available"]:
                    self.current_llm = llm_id
                    log("info", f"Current LLM changed to: {llm['name']} ({llm_id})")
                    return True
                else:
                    log("warning", f"LLM {llm_id} is not available (enabled: {llm['enabled']})")
                    return False

        log("error", f"LLM {llm_id} not found in available LLMs")
        return False

    def validate_config(self):
        """Validate the LLM configuration."""
        if "llms" not in self.config:
            log("error", "No 'llms' section in configuration")
            return False

        llms_config = self.config.get("llms", {})
        if not isinstance(llms_config, dict):
            log("error", f"'llms' section should be a dictionary, got: {type(llms_config)}")
            return False

        valid_count = 0
        for llm_id, llm_config in llms_config.items():
            if not isinstance(llm_config, dict):
                log("warning", f"LLM '{llm_id}' config is not a dictionary: {llm_config}")
                continue

            if "type" not in llm_config:
                log("warning", f"LLM '{llm_id}' missing 'type' field")
                continue

            if "model" not in llm_config:
                log("warning", f"LLM '{llm_id}' missing 'model' field")
                continue

            # Check if engine exists for this type
            engine_type = llm_config.get("type")
            if engine_type not in self.engines:
                log("warning", f"LLM '{llm_id}' uses unknown engine type: {engine_type}")
                continue

            valid_count += 1

        log("info", f"Validated {valid_count} LLM configurations")
        return valid_count > 0

    def get_llm_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Get LLM information by name."""
        available_llms = self.get_available_llms()

        for llm in available_llms:
            if llm["name"] == name:
                return llm

        return None

    def get_current_llm_info(self) -> Optional[Dict[str, Any]]:
        """Get information about the current LLM."""
        if not self.current_llm:
            return None

        available_llms = self.get_available_llms()
        for llm in available_llms:
            if llm["id"] == self.current_llm:
                return llm

        return None

    async def generate(self, message: str, stream_callback: Optional[Callable] = None) -> str:
        """Generate response from current LLM."""
        if not self.current_llm:
            error_msg = "No LLM selected"
            log("error", error_msg)
            return error_msg

        log("info", f"Generating response with current LLM: {self.current_llm}")
        log("debug", f"Message: {message[:100]}...")

        # Prepare messages for the LLM
        messages = [{"role": "user", "content": message}]

        return await self.generate_response(self.current_llm, messages, stream_callback)

    async def generate_response(self, llm_id: str, messages: list,
                               stream_callback: Optional[Callable] = None) -> str:
        """Generate response from selected LLM."""
        log("info", f"Generating response with LLM: {llm_id}")
        log("debug", f"Messages: {len(messages)} messages")

        llm_config = self.config.get("llms", {}).get(llm_id, {})
        llm_type = llm_config.get("type")
        model_name = llm_config.get("model")

        if not llm_config:
            error_msg = f"LLM {llm_id} not found in configuration"
            log("error", error_msg)
            return error_msg

        # Check if LLM is available (enabled and has required API key if needed)
        if not llm_config.get("enabled", True):
            error_msg = f"LLM {llm_id} is disabled"
            log("error", error_msg)
            return error_msg

        # Get the engine
        engine = self.get_engine(llm_type)
        if not engine:
            error_msg = f"No engine found for type: {llm_type}"
            log("error", error_msg)
            return error_msg

        # Check availability
        requires_api_key = llm_config.get("requires_api_key", False)
        if requires_api_key and not engine.is_available():
            error_msg = f"LLM {llm_id} requires API key which is not configured"
            log("error", error_msg)
            return error_msg

        # Filter empty messages
        filtered_messages = [msg for msg in messages if msg.get("content", "").strip()]

        if not filtered_messages:
            error_msg = "No valid messages provided"
            log("warning", error_msg)
            return error_msg

        # Generate response using the engine
        try:
            response = await engine.generate(model_name, filtered_messages, stream_callback)
            return response
        except Exception as e:
            error_msg = f"Error generating response from {llm_id}: {str(e)}"
            log("error", error_msg)
            return error_msg


# Global instance
_manager = None

def _get_manager():
    """Get or create the global LLMManager instance."""
    global _manager
    if _manager is None:
        _manager = LLMManager()
    return _manager

# Update all public functions to use _get_manager():
async def llm_generate(message: str, stream_callback: Optional[Callable] = None) -> str:
    """Simple interface to generate response from current LLM."""
    manager = _get_manager()
    return await manager.generate(message, stream_callback)

def set_current_llm(llm_id: str) -> bool:
    """Set the current LLM to use."""
    manager = _get_manager()
    return manager.set_current_llm(llm_id)

def get_available_llms() -> List[Dict[str, Any]]:
    """Get list of available LLMs."""
    manager = _get_manager()
    return manager.get_available_llms()

def get_current_llm_info() -> Optional[Dict[str, Any]]:
    """Get information about the current LLM."""
    manager = _get_manager()
    return manager.get_current_llm_info()

def get_llm_by_name(name: str) -> Optional[Dict[str, Any]]:
    """Get LLM information by name."""
    manager = _get_manager()
    return manager.get_llm_by_name(name)

# Alias for backward compatibility
llm = llm_generate

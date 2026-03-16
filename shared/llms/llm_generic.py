"""
Generic OpenAI-compatible LLM Engine

Supports any HTTP host that exposes the standard OpenAI API:
  GET  /v1/models
  POST /v1/chat/completions
  POST /v1/completions
  GET  /health

Configure via config.json:
  "type": "generic"
  "base_url": "http://127.0.0.1:5000/v1"   # full base URL including /v1
  "api_key": "none"                          # use "none" or "" for keyless servers
  "model": "deepseek_chat"
"""

import os
from typing import List, Dict, Any, Optional, Callable
from shared.llm_engine import LLMEngine, GenerateResult, _debug_log_messages
from core.logging import log

try:
    from openai import OpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False
    log("warning", "openai not installed, generic OpenAI-compatible engine disabled")


class GenericEngine(LLMEngine):
    """Generic engine for any OpenAI-compatible API host.

    The engine reads ``base_url`` and ``api_key`` directly from the per-LLM
    config dict that is passed when the LLMManager calls ``engine.generate()``.
    Because the same engine instance is shared across all ``"type": "generic"``
    LLM entries, the connection is created lazily on each call using the params
    embedded in ``messages`` metadata injected by the manager — actually, the
    manager passes model/config via the ``generate()`` signature so we store
    nothing on ``self`` that is config-entry-specific.

    In practice the manager calls ``generate(model, messages, ...)`` and looks
    up ``llm_config`` itself; it does **not** pass base_url/api_key through the
    ``generate`` signature.  We therefore read them from env vars **or** from
    extra keyword arguments forwarded by a thin wrapper (see ``_build_client``).

    To keep things simple we follow the same pattern as ``llm_xai.py``:
    the manager stores the full llm_config in ``self._pending_config`` just
    before calling ``generate``.  We provide ``set_config(cfg)`` for this.
    """

    DEFAULT_TEMPERATURE = 0.7
    DEFAULT_MAX_TOKENS = 1024
    _KEYLESS_SENTINELS = {"none", "no", "null", "", "false"}

    def __init__(self):
        super().__init__("generic")
        # Holds the config dict for the LLM entry currently being invoked.
        # Set by LLMManager via set_config() before each generate() call.
        self._active_config: Dict[str, Any] = {}
        self.available = HAS_OPENAI  # always "available" if openai is installed

    # ------------------------------------------------------------------
    # Config injection (called by LLMManager before generate)
    # ------------------------------------------------------------------

    def set_config(self, llm_config: Dict[str, Any]) -> None:
        """Store the per-entry config so generate() can read base_url/api_key."""
        self._active_config = llm_config or {}

    # ------------------------------------------------------------------
    # LLMEngine interface
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        """Always True when openai package is present; no key required."""
        return HAS_OPENAI

    def get_supported_models(self) -> List[str]:
        """Fetch the model list from the remote /v1/models endpoint if reachable."""
        client = self._build_client()
        if client is None:
            return []
        try:
            models = client.models.list()
            return [m.id for m in models.data]
        except Exception as e:
            log("warning", f"generic engine: could not fetch model list: {e}")
            return []

    async def generate(
        self,
        model: str,
        messages: List[Dict[str, str]],
        stream_callback: Optional[Callable] = None,
        response_format: Optional[str] = None,
        no_thinking: bool = False,
    ) -> GenerateResult:
        """Generate a response from a generic OpenAI-compatible endpoint.

        Args:
            model: Model name as configured (e.g. ``"deepseek_chat"``).
            messages: Conversation history in role/content format.
            stream_callback: Optional callable for incremental streaming chunks.
            response_format: Pass ``"json"`` to request ``{"type":"json_object"}``.
            no_thinking: Ignored — generic servers are assumed not to support it.

        Returns:
            GenerateResult where ``response == raw_response`` (no post-processing).
        """
        log("debug", f"generic engine: generating with model={model!r}")

        if not HAS_OPENAI:
            err = "openai package is not installed; cannot use generic engine"
            log("error", err)
            return GenerateResult(response=err, raw_response=err)

        client = self._build_client()
        if client is None:
            err = "generic engine: failed to build OpenAI client (check base_url)"
            log("error", err)
            return GenerateResult(response=err, raw_response=err)

        formatted = self._format_messages(messages)
        if not formatted:
            err = "generic engine: no valid messages provided"
            log("warning", err)
            return GenerateResult(response=err, raw_response=err)

        params: Dict[str, Any] = {
            "model": model,
            "messages": formatted,
            "temperature": self._active_config.get("temperature", self.DEFAULT_TEMPERATURE),
            "max_tokens": self._active_config.get("max_tokens", self.DEFAULT_MAX_TOKENS),
        }

        if response_format == "json":
            if stream_callback:
                log("warning", "generic engine: JSON mode not supported with streaming; ignoring")
            else:
                params["response_format"] = {"type": "json_object"}
                log("debug", "generic engine: JSON mode enabled")

        try:
            if stream_callback:
                log("debug", "generic engine: streaming mode")
                stream = client.chat.completions.create(**params, stream=True)
                text = self._handle_stream(stream, stream_callback)
            else:
                log("debug", "generic engine: non-streaming mode")
                completion = client.chat.completions.create(**params)
                text = completion.choices[0].message.content or ""

            text = text or "No response generated"
            log("debug", f"generic engine: response length={len(text)}")
            return GenerateResult(response=text, raw_response=text)

        except Exception as e:
            err = f"generic engine error: {e}"
            log("error", err)
            return GenerateResult(response=err, raw_response=err)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_client(self) -> Optional["OpenAI"]:
        """Construct an OpenAI-compatible client from the active config."""
        base_url = self._active_config.get("base_url") or os.getenv("GENERIC_LLM_BASE_URL", "")
        if not base_url:
            log("error", "generic engine: 'base_url' is required in the LLM config entry")
            return None

        raw_key = self._active_config.get("api_key") or os.getenv("GENERIC_LLM_API_KEY", "none")
        # Treat sentinel values as a dummy key so the openai client is happy
        api_key = "sk-no-key" if str(raw_key).strip().lower() in self._KEYLESS_SENTINELS else raw_key.strip()

        log("debug", f"generic engine: base_url={base_url!r}, keyless={api_key == 'sk-no-key'}")

        try:
            return OpenAI(api_key=api_key, base_url=base_url)
        except Exception as e:
            log("error", f"generic engine: failed to create client: {e}")
            return None

    def _format_messages(self, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
        """Strip unknown fields and ensure at least one user message exists."""
        if not messages:
            return []
        formatted = [{"role": m["role"], "content": m.get("content", "")} for m in messages if m.get("content", "").strip()]
        if not any(m["role"] == "user" for m in formatted):
            log("warning", "generic engine: no user message found, adding placeholder")
            formatted.append({"role": "user", "content": "Hello"})
        return formatted

    def _handle_stream(self, stream, callback: Callable) -> str:
        """Consume a streaming completion and forward chunks to ``callback``."""
        full = ""
        for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                part = chunk.choices[0].delta.content
                full += part
                callback(part)
        return full

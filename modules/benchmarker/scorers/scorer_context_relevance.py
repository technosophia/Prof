"""Context relevance scorer plugin."""

import asyncio
from collections import defaultdict
from statistics import mean
from typing import Dict, List

import yaml

from core.logging import log
from modules.benchmarker.scorers.base import ScorerPlugin as BaseScorerPlugin, ScoringResult
from shared.common import get_current_llm_id, get_llm_manager, get_prompt


class ScorerPlugin(BaseScorerPlugin):
    """LLM-based relevance scoring of injected contexts, aggregated per source."""

    id = "context_relevance"
    name = "Context Relevance (LLM)"

    def is_available(self) -> bool:
        return True

    def compute_score(self, session: Dict, config: Dict, container) -> None:
        session_path = config["session_path"]

        steps_with_context = [
            step
            for step in session.get("steps", [])
            if step.get("action") == "user_send_message" and step.get("injected_contexts")
        ]
        if not steps_with_context:
            container.warning("No user_send_message steps with injected context found in this session.")
            return

        sources = sorted(
            {
                str(entry.get("source", "unknown"))
                for step in steps_with_context
                for entry in (step.get("injected_contexts") or [])
            }
        )
        container.info(
            f"Found {len(steps_with_context)} step(s) with injected context. "
            f"Sources: {', '.join(sources) if sources else 'none'}"
        )

        batch_mode = bool(config.get("batch_mode"))
        submit_key = f"ctx_rel_submit_{session_path}"
        if not batch_mode and not container.button("Score context relevance", key=submit_key):
            return

        llm_id = get_current_llm_id()
        manager = get_llm_manager()

        scores_by_source: Dict[str, List[float]] = defaultdict(list)
        step_scores = []
        skipped = 0
        for step in steps_with_context:
            step_id = str(step.get("id", ""))
            user_message = str((step.get("params") or {}).get("content", ""))
            for entry in (step.get("injected_contexts") or []):
                source = str(entry.get("source", "unknown"))
                context_content = str(entry.get("content", ""))
                prompt = self._build_prompt(
                    user_message=user_message,
                    source=source,
                    context_content=context_content,
                )
                response_text, response_error = self._call_llm(manager, llm_id, prompt)
                if response_error:
                    log("warning", f"Context relevance LLM call failed for source '{source}': {response_error}")
                    skipped += 1
                    continue

                relevance = self._parse_relevance(response_text)
                if relevance is None:
                    log("warning", f"Context relevance parse failed for source '{source}'. Raw response: {response_text!r}")
                    skipped += 1
                    continue
                scores_by_source[source].append(float(relevance))
                step_scores.append({"step_id": step_id, "source": source, "relevance": float(relevance)})

        if not scores_by_source:
            container.warning("Could not compute any relevance score (all items failed to parse/call).")
            return

        aggregated_scores = {
            source: round(mean(values), 2)
            for source, values in sorted(scores_by_source.items())
            if values
        }

        for item in step_scores:
            step_result = ScoringResult(
                scorer_id=self.id,
                session_path=session_path,
                scores={"relevance": round(item["relevance"], 2)},
                scorer_config={
                    "level": "step",
                    "step_id": item["step_id"],
                    "source": item["source"],
                    "llm_id": llm_id,
                },
                source="llm_internal",
                notes=None,
                scored_at=self._now(),
                parse_errors=[],
                complete=True,
            )
            self._write_score(step_result)

        result = ScoringResult(
            scorer_id=self.id,
            session_path=session_path,
            scores=aggregated_scores,
            scorer_config={
                "llm_id": llm_id,
                "steps_evaluated": len(steps_with_context),
                "sources_found": sources,
                "level": "session",
            },
            source="llm_internal",
            notes=None,
            scored_at=self._now(),
            parse_errors=[],
            complete=True,
        )
        self._write_score(result)

        container.success(
            f"Context relevance scored for {len(aggregated_scores)} source(s). "
            f"Skipped {skipped} chunk(s) due to call/parse failures."
        )
        container.dataframe(
            [{"source": source, "relevance": score} for source, score in aggregated_scores.items()],
            width="stretch",
        )

    @staticmethod
    def _build_prompt(user_message: str, source: str, context_content: str) -> str:
        """Build the relevance scoring prompt using the multilingual prompt system.

        Falls back to a hardcoded English prompt if the key is not found,
        so the scorer remains functional even before prompts are loaded.
        """
        template = get_prompt("benchmarker.context_relevance_prompt")
        return template.format(
            user_message=user_message,
            source=source,
            context_content=context_content,
        )

    @staticmethod
    def _call_llm(manager, llm_id: str, prompt: str):
        messages = [{"role": "user", "content": prompt}]
        try:
            text = asyncio.run(manager.internal_response(llm_id, messages))
            return text, None
        except RuntimeError:
            loop = asyncio.new_event_loop()
            try:
                text = loop.run_until_complete(manager.internal_response(llm_id, messages))
                return text, None
            finally:
                loop.close()
        except Exception as exc:
            return "", f"LLM call failed: {exc}"

    @staticmethod
    def _parse_relevance(text: str):
        try:
            cleaned = (text or "").strip()
            if cleaned.startswith("```"):
                lines = cleaned.splitlines()
                cleaned = "\n".join(line for line in lines if not line.strip().startswith("```"))
            parsed = yaml.safe_load(cleaned) or {}
            value = parsed.get("relevance")
            if value is None:
                return None
            return float(value)
        except Exception as exc:
            log("warning", f"Error parsing relevance from response: {exc}", exc_info=True)
            return None

<!-- /_docs/ADR_PROMPT_CONFIG_NAMESPACE.md -->
## Purpose
Document the decision to make config/prompt key namespaces independent from directory paths and align all module call sites with content-defined keys.

## Context
Previously, `core/config.py` and `shared/prompt_manager.py` derived namespaces from filesystem paths.
That made module moves/renames risky because key resolution changed without explicit code changes.

## Decision
- **Config loading** now performs a flat root merge.
  - `config.json` files contribute keys from their own JSON content only.
  - No path-derived prefix is added.
  - Legacy wrapped files with a single top-level dict key are auto-flattened one level.
- **Prompt loading** now performs a flat root merge per language.
  - `prompts.yaml` and `prompts.<lang>.yaml` contribute keys from YAML top-level keys only.
  - No path-derived or module-derived namespace is added.
- **Call-site nomenclature** is updated across modules:
  - `config.get("modules.<module>....")` → content-based keys (for example `config.get("rag_manager")` or scalar keys like `config.get("dataset_dir")`).
  - `get_prompt("<module>....")` → content-based keys (for example `get_prompt("teacher.system_prompt")`, `get_prompt("analysis_system")`, `get_prompt("judge_prompt")`).

## Consequences
- Renaming/moving directories no longer changes key lookup behavior.
- Namespacing responsibility is now explicit in file content (`config.json` / `prompts.*.yaml`).
- Key collisions must be managed at content level (top-level JSON/YAML keys should remain distinct).

## Do / Don't
- **Do** namespace keys explicitly in file content when needed to avoid collisions.
- **Do** keep prompt/config lookups aligned with file top-level structures.
- **Don't** reconstruct namespaces from paths.
- **Don't** rely on directory names as implicit key prefixes.

## Migration notes
- Existing module call sites were updated to the new content-based keys.
- Future modules should define stable top-level keys directly in config/prompt files.

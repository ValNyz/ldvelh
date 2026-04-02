# Test Coverage Report

Generated: 2026-04-02 | 780 tests | **93% overall** | 217s runtime

## Summary

| Category | Files | Avg Coverage |
|----------|-------|-------------|
| Schemas | 9 | 97% |
| Services | 8 | 87% |
| Prompts | 5 | 96% |
| API | 5 | 62% |
| KG (Knowledge Graph) | 4 | 75% |
| Utils | 5 | 98% |
| Tests | 18 | ~100% |

## Source Files

| File | Stmts | Miss | Cover | Missing Lines |
|------|-------|------|-------|---------------|
| **API** | | | | |
| api/__init__.py | 3 | 0 | 100% | |
| api/auth.py | 165 | 42 | 75% | 86-89, 101, 185-186, 196-212, 226-238, 251-260, 275-297, 349 |
| api/dependencies.py | 37 | 8 | 78% | 24-25, 30, 46, 52, 60, 72, 77 |
| api/routes.py | 269 | 172 | **36%** | 56-71, 142, 220-221, 227-229, 265-268, 281-305, 310-714 |
| api/streaming.py | 143 | 7 | 95% | 152-158, 214 |
| api/tooltips.py | 77 | 19 | 75% | 186-246, 259-296 |
| **Config** | | | | |
| config.py | 31 | 0 | 100% | |
| main.py | 41 | 15 | 63% | 29-51, 76, 91, 95-97 |
| **Knowledge Graph** | | | | |
| kg/__init__.py | 4 | 0 | 100% | |
| kg/populator.py | 292 | 65 | 78% | World population edge cases |
| kg/reader.py | 249 | 89 | **64%** | Several query methods untested |
| kg/specialized_populator.py | 259 | 43 | 83% | Some extraction edge cases |
| **Prompts** | | | | |
| prompts/__init__.py | 4 | 0 | 100% | |
| prompts/examples.py | 13 | 0 | 100% | |
| prompts/extractor_prompts.py | 62 | 5 | 92% | Narrator hint flags |
| prompts/narrator_prompt.py | 225 | 0 | 100% | |
| prompts/shared.py | 4 | 0 | 100% | |
| prompts/world_generation_prompt.py | 40 | 5 | 88% | Template edge cases |
| **Schemas** | | | | |
| schema/__init__.py | 9 | 0 | 100% | |
| schema/core.py | 176 | 1 | 99% | |
| schema/entities.py | 130 | 0 | 100% | |
| schema/extraction.py | 159 | 1 | 99% | |
| schema/narration.py | 162 | 0 | 100% | |
| schema/narrative.py | 68 | 2 | 97% | |
| schema/relations.py | 16 | 0 | 100% | |
| schema/sse_payload.py | 52 | 0 | 100% | |
| schema/synonyms.py | 24 | 4 | 83% | |
| schema/world_generation.py | 258 | 6 | 98% | |
| **Services** | | | | |
| services/__init__.py | 1 | 0 | 100% | |
| services/auth_service.py | 77 | 1 | 99% | |
| services/context_builder.py | 149 | 15 | 90% | |
| services/email_service.py | 23 | 0 | 100% | |
| services/extraction_service.py | 205 | 20 | 90% | |
| services/game_service.py | 297 | 16 | 95% | |
| services/llm_providers.py | 225 | 61 | **73%** | Real provider methods (stream, complete) |
| services/llm_service.py | 185 | 22 | 88% | |
| services/state_normalizer.py | 127 | 9 | 93% | |
| **Utils** | | | | |
| utils/__init__.py | 2 | 0 | 100% | |
| utils/crypto.py | 23 | 0 | 100% | |
| utils/json_utils.py | 249 | 0 | 100% | |
| utils/rate_limit.py | 23 | 2 | 91% | |
| utils/time_utils.py | 15 | 0 | 100% | |

## Coverage Gaps

### Low coverage (needs E2E tests)
- **api/routes.py (36%)** — `_handle_chat` core flow, SSE streaming, world generation endpoint. These require full E2E tests with mocked LLM.
- **kg/reader.py (64%)** — Several DB query methods only exercised indirectly through integration tests.
- **llm_providers.py (73%)** — Real provider `stream()`/`complete()` methods can't be tested without API keys.
- **main.py (63%)** — Lifespan startup/shutdown, CORS setup.

### Effectively untestable without real APIs
- Provider `stream()`, `complete()`, `complete_with_tools()`, `complete_with_schema()` methods
- These are integration-tested in production, mocked in tests

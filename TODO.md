# LDVELH — Remaining Work

## Next Up

### 13. Tests E2E
End-to-end tests covering the full API flow with mocked LLM.
- Create game → generate world → send messages → extraction → rollback
- Verify SSE streaming, auth guards, error handling
- Mocked LLM responses (no real API calls)

### 14. Frontend Adaptation & Decoupling
- French keys in state normalizer → align with backend contract
- SSE format consistency (live vs reload message shape)
- State management cleanup

## Deferred

- **Tooltip re-enable** — feature disabled, code kept in Message.jsx / useTooltips.js / EntityTooltip.jsx
- **World gen parameterization** — `mandatory_npcs=None` hardcoded in routes.py:343, let user pick NPCs/locations before world gen

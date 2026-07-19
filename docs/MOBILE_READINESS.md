# Mobile Readiness Checklist

Current status:

- Tools do not expose model-controlled `user_id`.
- Critical behavior has automated tests.
- Progression is agent-proposed, backend-validated, and has a deterministic fallback.
- Routines support structured drafts and explicit confirmation.
- Sessions have IDs, states, and idempotent finish behavior.
- Agent responses have a neutral `AgentResponse` contract.
- Prompt base is independent of Telegram formatting.
- Agent execution is available through a reusable service and `/api/agent/message`.
- Users have internal UUIDs and external identities.
- PostgreSQL dependencies, Alembic scaffolding, and optional Postgres checkpointer are present.
- Structured logs and eval cases exist.

Remaining infrastructure work:

- Run Alembic against real PostgreSQL with production credentials.
- Exercise the Postgres checkpointer in a deployed environment.
- Decide mobile authentication provider before replacing Telegram token flows.
- Add richer eval cases as prompt behavior changes.

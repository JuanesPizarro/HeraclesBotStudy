# Mobile Readiness Checklist

Current status:

- Tools do not expose model-controlled `user_id`.
- Critical behavior has automated tests.
- Progression is agent-proposed, backend-validated, and has a deterministic fallback.
- Exercise names are documented as stable persistence keys for workouts and progression.
- Routines support structured drafts and explicit confirmation.
- Calendar-only routine changes are applied directly after confirmation and do not create drafts.
- Sessions have IDs, states, and idempotent finish behavior.
- Agent responses have a neutral `AgentResponse` contract.
- Prompt base is independent of Telegram formatting.
- Agent execution is available through a reusable service and `/api/agent/message`.
- Users have internal UUIDs and external identities.
- PostgreSQL dependencies, Alembic scaffolding, and optional Postgres checkpointer are present.
- Structured logs and eval cases exist.
- Mobile API V1 surface and response contracts are documented in `docs/MOBILE_API_V1.md`.
- `/api/v1` mobile endpoints exist for profile, session plan, set logging,
  today's sets, session finish and agent messages.
- Expo client MVP exists in `mobile/` with Today, Coach and Profile screens.

Remaining infrastructure work:

- Run Alembic against real PostgreSQL with production credentials.
- Exercise the Postgres checkpointer in a deployed environment.
- Decide mobile authentication provider before replacing Telegram token flows.
- Exercise the Expo client on a physical device against production.
- Add production-grade error reporting for Telegram/model/tool failures.
- Add richer eval cases as prompt behavior changes.

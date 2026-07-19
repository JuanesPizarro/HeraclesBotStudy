# MCP Decision

MCP is intentionally not implemented for the current Heracles backend.

Rationale:

- Tools run in the same process as the agent and database.
- MCP does not solve identity, prompt safety, deterministic progression, validation, memory, or idempotency.
- Adding MCP now would increase authentication, latency, and operational surface area before the mobile API is stable.

Revisit MCP when another authorized agent or service needs to consume Heracles capabilities, or when integrations such as calendars, wearables, or exercise catalogs are split into separately operated services.

Before exposing writes through MCP, the backend must keep identity, permissions, audit logs, idempotency, and user isolation enforced in code.

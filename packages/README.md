# Packages

Shared libraries used by more than one service.

| Package | Purpose | Status |
|---|---|---|
| `shared/` | Common pydantic models, typed HTTP clients, constants | to be created alongside the first cross-service need |

Keep this directory **small**. If only one service needs something, it
lives in that service. Packages come into existence when duplication
appears across services — not speculatively.

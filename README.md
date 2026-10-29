
# ClaimSage

ClaimSage is an AI-powered insurance employee assistant.

## Initial scope

- Evidence-grounded policy and procedure question answering
- Permission-controlled claim information retrieval
- Deterministic missing-document checklists
- AI-assisted customer email drafting
- Human review and approval workflows
- Auditable actions and decisions

## Safety boundaries

- No automated claim approval or denial
- No automated coverage or settlement decisions
- No automatic sending of customer emails
- Synthetic demonstration data only during development

## Technology

- Frontend: React, TypeScript, Vite
- Backend: Python, FastAPI, Pydantic
- Database: PostgreSQL with pgvector
- Agent orchestration: LangGraph
- Local infrastructure: Docker Compose

## Development status

Initial project setup. Features are implemented and validated incrementally.
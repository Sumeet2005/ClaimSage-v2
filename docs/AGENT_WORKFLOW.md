# ClaimSage Multi-Agent Workflow Specification

This document provides an in-depth breakdown of the six specialist agents, the Supervisor, and the LangGraph orchestration engine.

---

## 1. Specialist Agents Breakdown

### 1.1 Supervisor Agent (`supervisor.py`)
- **Input**: Claim facts, task description, document types available.
- **Contract**: `SupervisorPlan` (`selected_analysts`, `routing_rationale`, `human_review_required`).
- **Logic**: Inspects claim metadata. Motor claims with an estimate document route through `repair_estimate_analyst`. Health claims automatically bypass repair analysis.

### 1.2 Claim Intake Agent (`intake_agent.py`)
- **Input**: Claim header facts and raw document passages.
- **Contract**: `IntakeDocumentOutput` (`document_inventory`, `missing_information`, `data_quality_issues`).
- **Logic**: Verifies legibility, checks for mandatory initial documents (e.g., Discharge Summary, Final Bill), and flags missing intake data.

### 1.3 Evidence Analyst (`evidence_analyst.py`)
- **Input**: Retrieved claim evidence chunks.
- **Contract**: `EvidenceAnalystOutput` (`observed_facts`, `timeline`, `conflicts`, `evidence_gaps`).
- **Logic**: Constructs a chronological clinical or incident timeline with verified `evidence_id` citations and flags contradictory assertions across documents.

### 1.4 Policy Analyst (`policy_analyst.py`)
- **Input**: Retrieved policy clauses, claim facts, and claim evidence.
- **Contract**: `PolicyAnalystOutput` (`coverage_indicators`, `exclusions_and_conditions`, `missing_information`, `evidence_gaps`).
- **Logic**: Evaluates policy rules against claim facts, surfacing room-rent sub-limits, deductible clauses, and specific exclusions.

### 1.5 Repair Estimate Analyst (`repair_estimate_analyst.py`)
- **Input**: Vehicle repair estimate text and policy coverage limits.
- **Contract**: `RepairEstimateAnalystOutput` (`line_items`, `labor_subtotal`, `parts_subtotal`, `deductible_applied`).
- **Logic**: Runs deterministic rule checks (`repair_estimate_rules.py`) combined with line-item extraction to detect inflated labor hours or invalid parts prices.

### 1.6 Risk & Anomaly Agent (`risk_anomaly_agent.py`)
- **Input**: Claim facts and evidence.
- **Contract**: `RiskAnomalyOutput` (`observed_facts`, `anomalies`, `hypotheses`, `missing_information`).
- **Logic**: Surfaces discrepancies while maintaining a hard boundary between observed facts and speculative hypotheses. Strictly prohibited from emitting fraud allegations.

### 1.7 Review & Report Agent (`review_report_agent.py`)
- **Input**: Structured outputs from all upstream completed specialists.
- **Contract**: `ReviewReportOutput` (`observed_facts`, `analyst_interpretations`, `hypotheses`, `conflicting_findings`, `missing_information`, `report_status`).
- **Logic**: Synthesizes the final executive report. Validates verbatim quote matches and RFC 6901 JSON Pointers (`output_path`).

---

## 2. Shared Evidence Reconciliation
Before finalizing the report, `reconcile_specialist_missing_in_state` inspects items marked as "missing" by any agent. If another specialist or document retrieval has already verified that fact, the missing-information entry is classified into:
- `retrieved`: Fact is available in evidence.
- `partially_available`: Partial data found.
- `not_provided`: Truly missing from claim file.

---

## 3. Deterministic Fallback Mode
If cloud LLM rate limits or network issues prevent AI report synthesis, `build_fallback_partial_report()` aggregates all completed specialist findings into a valid `ReviewReportOutput`.
- The report status is marked `incomplete`.
- The generation mode is recorded as `report_generation_mode="deterministic_fallback"`.
- Zero artificial or hallucinated findings are introduced.

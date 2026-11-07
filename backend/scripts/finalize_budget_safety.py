"""Definitive compaction for review_report_agent.py."""

from pathlib import Path

BACKEND_DIR = Path("backend/src/claimsage/agents")
rr_path = BACKEND_DIR / "review_report_agent.py"
rr_text = rr_path.read_text(encoding="utf-8").replace("\r\n", "\n")

old_block = """    compact_specialists: dict[str, object] = {}
    for name in _SPECIALISTS:
        spec = getattr(report_input, name)
        if spec.status in {"completed", "insufficient_evidence"}:
            if spec.analysis is not None:
                analysis_data = _to_dict(spec.analysis)
                if "summary" in analysis_data:
                    analysis_data["summary"] = str(analysis_data["summary"])[:150]
                if name == "policy_analyst":
                    analysis_data.pop("summary_quotes", None)
                    analysis_data.pop("assessment_quotes", None)
                    for key in ("relevant_clauses", "coverage_indicators", "exclusions_and_conditions"):
                        if isinstance(analysis_data.get(key), list):
                            analysis_data[key] = analysis_data[key][:2]
                elif name == "risk_anomaly_agent":
                    for group_key in ("observed_facts", "potential_inconsistencies", "anomalies", "human_verification_hypotheses", "hypotheses", "missing_information"):
                        items = analysis_data.get(group_key)
                        if isinstance(items, list):
                            for it in items:
                                if isinstance(it, dict):
                                    it.pop("supporting_quotes", None)
                            analysis_data[group_key] = items[:2]
                elif name == "evidence_analyst":
                    analysis_data.pop("summary_quotes", None)
                    analysis_data.pop("assessment_quotes", None)
                    if isinstance(analysis_data.get("factual_findings"), list):
                        analysis_data["factual_findings"] = analysis_data["factual_findings"][:2]
                    if isinstance(analysis_data.get("timeline"), list):
                        analysis_data["timeline"] = analysis_data["timeline"][:2]
                elif name == "intake_agent":
                    if isinstance(analysis_data.get("extracted_fields"), list):
                        analysis_data["extracted_fields"] = analysis_data["extracted_fields"][:3]
                    if isinstance(analysis_data.get("document_inventory"), list):
                        analysis_data["document_inventory"] = analysis_data["document_inventory"][:2]

                compact_specialists[name] = {
                    "status": spec.status,
                    "analysis": analysis_data,
                }
            else:
                compact_specialists[name] = {"status": spec.status}"""

new_block = """    def _compact_completed_specialist_analysis(spec_name: str, raw: dict[str, object]) -> dict[str, object]:
        clean: dict[str, object] = {}
        if "summary" in raw:
            clean["summary"] = str(raw["summary"])[:100]
        if "status" in raw:
            clean["status"] = raw["status"]
        if "overall_status" in raw:
            clean["overall_status"] = raw["overall_status"]
        if "overall_assessment" in raw:
            clean["overall_assessment"] = raw["overall_assessment"]
        if "human_review_required" in raw:
            clean["human_review_required"] = raw["human_review_required"]

        if spec_name == "intake_agent":
            if "extracted_fields" in raw and isinstance(raw["extracted_fields"], list):
                clean["extracted_fields"] = [
                    {
                        "field_name": f.get("field_name"),
                        "value": str(f.get("value", ""))[:50],
                        "source_evidence_ids": f.get("source_evidence_ids", []),
                    }
                    for f in raw["extracted_fields"][:2] if isinstance(f, dict)
                ]
            if "document_flags" in raw and isinstance(raw["document_flags"], list):
                clean["document_flags"] = [
                    {"description": str(d.get("description", ""))[:80]}
                    for d in raw["document_flags"][:1] if isinstance(d, dict)
                ]
        elif spec_name == "evidence_analyst":
            if "factual_findings" in raw and isinstance(raw["factual_findings"], list):
                clean["factual_findings"] = [
                    {
                        "finding": str(f.get("finding", ""))[:100],
                        "supporting_evidence_ids": f.get("supporting_evidence_ids", []),
                    }
                    for f in raw["factual_findings"][:2] if isinstance(f, dict)
                ]
        elif spec_name == "policy_analyst":
            if "relevant_clauses" in raw and isinstance(raw["relevant_clauses"], list):
                clean["relevant_clauses"] = [
                    {
                        "finding": str(c.get("finding", ""))[:100],
                        "supporting_evidence_ids": c.get("supporting_evidence_ids", []),
                    }
                    for c in raw["relevant_clauses"][:2] if isinstance(c, dict)
                ]
        elif spec_name == "risk_anomaly_agent":
            if "anomalies" in raw and isinstance(raw["anomalies"], list):
                clean["anomalies"] = [
                    {
                        "finding": str(a.get("finding", ""))[:100],
                        "supporting_evidence_ids": a.get("supporting_evidence_ids", []),
                    }
                    for a in raw["anomalies"][:2] if isinstance(a, dict)
                ]
            if "hypotheses" in raw and isinstance(raw["hypotheses"], list):
                clean["hypotheses"] = [
                    {"finding": str(h.get("finding", ""))[:100]}
                    for h in raw["hypotheses"][:1] if isinstance(h, dict)
                ]
        elif spec_name == "repair_estimate_analyst":
            if "line_items" in raw and isinstance(raw["line_items"], list):
                clean["line_items"] = [
                    {"part_description": str(item.get("part_description", ""))[:50]}
                    for item in raw["line_items"][:2] if isinstance(item, dict)
                ]
            if "findings" in raw and isinstance(raw["findings"], list):
                clean["findings"] = [
                    {"finding": str(f.get("finding", ""))[:100]}
                    for f in raw["findings"][:2] if isinstance(f, dict)
                ]

        for k, v in raw.items():
            if k not in clean and k not in {"summary_quotes", "assessment_quotes", "sources", "timeline", "inconsistencies", "missing_information", "evidence_gaps", "document_inventory"}:
                if isinstance(v, list):
                    clean[k] = v[:2]
                else:
                    clean[k] = v
        return clean

    compact_specialists: dict[str, object] = {}
    for name in _SPECIALISTS:
        spec = getattr(report_input, name)
        if spec.status in {"completed", "insufficient_evidence"}:
            if spec.analysis is not None:
                analysis_data = _to_dict(spec.analysis)
                if spec.status == "completed":
                    analysis_data = _compact_completed_specialist_analysis(name, analysis_data)
                compact_specialists[name] = {
                    "status": spec.status,
                    "analysis": analysis_data,
                }
            else:
                compact_specialists[name] = {"status": spec.status}"""

assert old_block in rr_text, "old_block not found in review_report_agent.py"
rr_text = rr_text.replace(old_block, new_block, 1)
rr_path.write_text(rr_text, encoding="utf-8", newline="\n")
print("Successfully applied definitive compaction to review_report_agent.py")

"""Restore policy evidence metadata fields while keeping 3-chunk compaction."""

from pathlib import Path

BACKEND_DIR = Path("backend/src/claimsage/agents")
policy_path = BACKEND_DIR / "policy_analyst.py"
policy_text = policy_path.read_text(encoding="utf-8").replace("\r\n", "\n")

old_policy = """        evidence_for_model.append(
            {
                "evidence_id": evidence_id,
                "clause_id": evidence.get("clause_id"),
                "clause_identifier": evidence.get("clause_identifier"),
                "clause_category": evidence.get("clause_category"),
                "filename": evidence.get("filename"),
                "page_number": evidence.get("page_number"),
                "text": evidence_text,
            }
        )"""

new_policy = """        evidence_for_model.append(
            {
                "evidence_id": evidence_id,
                "filename": evidence.get("filename"),
                "page_number": evidence.get("page_number"),
                "clause_id": evidence.get("clause_id"),
                "clause_identifier": evidence.get("clause_identifier"),
                "clause_category": evidence.get("clause_category"),
                "verification_status": evidence.get("verification_status"),
                "policy_version": evidence.get("policy_version"),
                "source_url": evidence.get("source_url"),
                "insurer_name": evidence.get("insurer_name"),
                "product_name": evidence.get("product_name"),
                "policy_identifier": evidence.get("policy_identifier"),
                "effective_from": evidence.get("effective_from"),
                "effective_to": evidence.get("effective_to"),
                "text": evidence_text,
            }
        )"""

assert old_policy in policy_text, "old_policy block not found"
policy_text = policy_text.replace(old_policy, new_policy, 1)
policy_path.write_text(policy_text, encoding="utf-8", newline="\n")
print("Restored metadata fields in policy_analyst.py")

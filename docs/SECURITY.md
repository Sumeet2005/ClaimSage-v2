# ClaimSage Security & Compliance Architecture

This document describes the security controls, boundary enforcement, and privacy mechanisms implemented across ClaimSage.

---

## 1. Decision Boundaries & Autonomous Action Prevention
ClaimSage is strictly a decision-support platform. The codebase contains programmatic safeguards that make autonomous claim settlement impossible:
1. **No Settlement Endpoints**: The backend contains no endpoints or database fields capable of issuing claim disbursements, approving payments, or issuing denial letters without authenticated human intervention.
2. **Prohibited Language Filter**: The `ReviewReportAgent` scans model output against regex patterns for forbidden adjudicative terms (`claim approved`, `claim denied`, `settled`, `fraudulent`, `liable`, etc.).
3. **Mandatory Human Review**: The `human_review_required` attribute is immutable and set to `true` on all specialist outputs.

---

## 2. Authentication & Authorization (RBAC)
- **Token Security**: Tokens are signed using HS256 with a minimum 32-character secret (`JWT_SECRET_KEY`) and expire after 30 minutes.
- **Password Storage**: Passwords are never stored in plain text; they are hashed using modern password hashing algorithms (Argon2 / Bcrypt).
- **Role Scoping**:
  - `claims_adjuster`: Restricted to assigned claims.
  - `policy_specialist`: Authorized to verify policy clauses.
  - `admin`: Authorized for audit events and employee management.

---

## 3. Data Privacy & Synthetic Data Standard
- **No Real Claimant Data**: All demo claims, policies, bills, and names are generated synthetically.
- **Email Sandbox**: `EMAIL_BACKEND=sandbox` intercepts all outbound communications, writing them to a database table instead of an SMTP transport.
- **Tenant Isolation**: Vector search queries always include mandatory SQL `WHERE claim_id = :claim_id` clauses to prevent cross-claim data leakage.

---

## 4. Secret & Environment Variable Management
- Real keys (`GROQ_API_KEY`, `GEMINI_API_KEY`, `JWT_SECRET_KEY`) must reside exclusively in `.env`, which is strictly ignored by `.gitignore`.
- `.env.example` contains only placeholder values (`change-this-local-password`).
- Automated tests run with `CLAIMSAGE_DISABLE_DOTENV=1`, preventing test runs from reading local developer secrets.

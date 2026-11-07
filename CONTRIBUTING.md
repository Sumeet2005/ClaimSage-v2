# Contributing to ClaimSage

Thank you for contributing to ClaimSage. Please read these guidelines before submitting a pull request or contributing to the codebase.

---

## 1. Development Principles
- **Maintain Safety Guardrails**: Never add features that allow AI agents to autonomously approve, deny, settle, or pay claims.
- **Evidence Provenance**: Any code adding new finding types must support canonical `evidence_id` attribution and verbatim source quotes.
- **Strict Privacy**: Never commit real claimant data, personal documents, or private keys.

---

## 2. Pull Request Workflow
1. Fork the repository and create a descriptive branch:
   ```bash
   git checkout -b feature/your-feature-name
   ```
2. Make your changes adhering to PEP 8 standards (Python) and ESLint/Prettier (TypeScript).
3. Ensure all tests pass:
   ```powershell
   # Run backend tests
   pytest backend/tests -q

   # Run frontend validation
   cd frontend
   npm run typecheck
   npm run build
   ```
4. Verify no secrets or sensitive files are staged (`git status`, `.gitignore`).
5. Submit your pull request with a detailed description of changes and test evidence.

---

## 3. Reporting Issues
Please report issues with:
- Clear steps to reproduce the problem.
- Expected behavior vs actual behavior.
- Relevant anonymized logs (ensure all API keys and personal identifiers are removed).

import { useState } from 'react'
import {
  ShieldCheck,
  Copy,
  Check,
} from 'lucide-react'

export function DocumentationSection() {
  const [activeDoc, setActiveDoc] = useState<'quickstart' | 'api' | 'contracts' | 'fallback'>('quickstart')
  const [copied, setCopied] = useState(false)

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <section id="docs" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
            Engineering Reference
          </p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
            Documentation & Developer Specifications.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
            Review container orchestration procedures, REST API schemas, and multi-agent contract specifications.
          </p>
        </div>

        {/* Tab Controls */}
        <div className="mt-10 flex flex-wrap gap-2 border-b border-[#E9E5DB] pb-4">
          <button
            type="button"
            onClick={() => setActiveDoc('quickstart')}
            className={`rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeDoc === 'quickstart'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            Docker Compose Quickstart
          </button>
          <button
            type="button"
            onClick={() => setActiveDoc('api')}
            className={`rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeDoc === 'api'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            REST API Contracts
          </button>
          <button
            type="button"
            onClick={() => setActiveDoc('contracts')}
            className={`rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeDoc === 'contracts'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            LangGraph State Schemas
          </button>
          <button
            type="button"
            onClick={() => setActiveDoc('fallback')}
            className={`rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeDoc === 'fallback'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            Deterministic Fallback Mode
          </button>
        </div>

        {/* Content Card */}
        <div className="mt-6 rounded-3xl border border-[#E9E5DB] bg-white p-6 sm:p-8 shadow-sm">
          {activeDoc === 'quickstart' && (
            <div>
              <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                <h3 className="font-display text-xl font-semibold text-[#18211D]">
                  Running the Full Stack with Docker Compose
                </h3>
                <button
                  type="button"
                  onClick={() =>
                    copyToClipboard(
                      'cp .env.example .env\ndocker compose up --build -d\ncurl http://localhost:8080/health/'
                    )
                  }
                  className="inline-flex items-center gap-1.5 rounded-lg border border-[#E9E5DB] bg-[#FAF9F6] px-3 py-1.5 text-xs font-medium text-[#18211D] hover:bg-white"
                >
                  {copied ? <Check className="size-3.5 text-[#397454]" /> : <Copy className="size-3.5" />}
                  <span>{copied ? 'Copied' : 'Copy Commands'}</span>
                </button>
              </div>

              <p className="mt-4 text-xs leading-relaxed text-[#6F7770]">
                ClaimSage spins up 5 isolated services: frontend Nginx on port 8080, FastAPI backend on 8000, async worker, PostgreSQL with pgvector on 5432, and MinIO S3 on 9000.
              </p>

              <pre className="mt-4 overflow-x-auto rounded-2xl bg-[#191C19] p-5 font-mono text-xs text-[#FAF9F6] leading-relaxed">
                <code>{`# 1. Clone repository & configure environment variables
git clone https://github.com/Sumeet2005/ClaimSage-v2.git
cd ClaimSage-v2
cp .env.example .env

# 2. Build and launch all container services
docker compose up --build -d

# 3. Verify healthcheck statuses
docker compose ps
curl http://localhost:8080/health/

# 4. Access ClaimSage Workspace
# Open http://localhost:8080 in your browser`}</code>
              </pre>
            </div>
          )}

          {activeDoc === 'api' && (
            <div>
              <h3 className="font-display text-xl font-semibold text-[#18211D] border-b border-[#E9E5DB] pb-4">
                Core REST API Endpoints (`/api/v1`)
              </h3>
              <div className="mt-6 space-y-3">
                {[
                  { method: 'POST', path: '/api/v1/auth/login', desc: 'Authenticates employee and establishes in-memory session.' },
                  { method: 'GET', path: '/api/v1/claims', desc: 'Lists authorized claims assigned to current adjuster account.' },
                  { method: 'POST', path: '/api/v1/investigations', desc: 'Launches asynchronous LangGraph investigation run.' },
                  { method: 'GET', path: '/api/v1/investigations/{id}', desc: 'Fetches multi-tab report, specialist states, and citations.' },
                  { method: 'POST', path: '/api/v1/investigations/{id}/review', desc: 'Records licensed adjuster sign-off and overrides.' },
                  { method: 'GET', path: '/api/v1/policies', desc: 'Retrieves active versioned policies and clause schedules.' },
                ].map((ep) => (
                  <div key={ep.path} className="flex flex-col sm:flex-row sm:items-center justify-between rounded-xl border border-[#E9E5DB] bg-[#FAF9F6] p-3 text-xs gap-2">
                    <div className="flex items-center gap-3">
                      <span className="rounded bg-[#183F32] px-2 py-0.5 font-mono text-[10px] font-bold text-white">
                        {ep.method}
                      </span>
                      <code className="font-mono text-[#18211D] font-semibold">{ep.path}</code>
                    </div>
                    <span className="text-[#6F7770]">{ep.desc}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {activeDoc === 'contracts' && (
            <div>
              <h3 className="font-display text-xl font-semibold text-[#18211D] border-b border-[#E9E5DB] pb-4">
                LangGraph State & Pydantic Validation Schemas
              </h3>
              <p className="mt-4 text-xs leading-relaxed text-[#6F7770]">
                Located in `backend/src/claimsage/agents/schemas.py`. All specialist outputs must adhere strictly to these models:
              </p>
              <pre className="mt-4 overflow-x-auto rounded-2xl bg-[#FAF9F6] p-5 font-mono text-xs text-[#18211D] border border-[#E9E5DB] leading-relaxed">
                <code>{`class InvestigationGraphState(TypedDict):
    claim_id: UUID
    claim_facts: ClaimFacts
    supervisor_plan: SupervisorPlan
    intake_output: Optional[IntakeDocumentOutput]
    evidence_output: Optional[EvidenceAnalystOutput]
    policy_output: Optional[PolicyAnalystOutput]
    repair_output: Optional[RepairEstimateAnalystOutput]
    risk_output: Optional[RiskAnomalyOutput]
    final_report: Optional[ReviewReportOutput]
    generation_mode: Literal["ai_synthesis", "deterministic_fallback"]
    human_review_required: bool`}</code>
              </pre>
            </div>
          )}

          {activeDoc === 'fallback' && (
            <div>
              <h3 className="font-display text-xl font-semibold text-[#18211D] border-b border-[#E9E5DB] pb-4">
                Deterministic Fallback Mode Guarantee
              </h3>
              <p className="mt-4 text-xs leading-relaxed text-[#6F7770]">
                Implemented in `build_fallback_partial_report()` (`backend/src/claimsage/agents/review_report_agent.py`):
              </p>
              <ul className="mt-4 space-y-3 text-xs text-[#18211D]">
                <li className="flex items-start gap-2.5 rounded-xl border border-[#DDE9DF] bg-[#DDE9DF]/20 p-3">
                  <ShieldCheck className="mt-0.5 size-4 text-[#183F32] shrink-0" />
                  <span><strong>Zero Hallucinated Findings:</strong> When external cloud LLMs encounter HTTP 429 rate limits, upstream verified specialist outputs are compiled deterministically into the final report structure.</span>
                </li>
                <li className="flex items-start gap-2.5 rounded-xl border border-[#DDE9DF] bg-[#DDE9DF]/20 p-3">
                  <ShieldCheck className="mt-0.5 size-4 text-[#183F32] shrink-0" />
                  <span><strong>Explicit Mode Flag:</strong> Sets <code>generation_mode = "deterministic_fallback"</code> and <code>report_status = "incomplete"</code> so adjusters immediately know synthesis was algorithmic.</span>
                </li>
              </ul>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}

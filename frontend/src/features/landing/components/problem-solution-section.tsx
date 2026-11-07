import { useState } from 'react'
import {
  CheckCircle2,
  XCircle,
} from 'lucide-react'

export function ProblemSolutionSection() {
  const [activeTab, setActiveTab] = useState<number>(0)

  const comparisons = [
    {
      id: 'fragmentation',
      title: 'Scattered Claim Evidence',
      challenge: {
        heading: 'Disconnected, Unstructured Files',
        points: [
          'Hospital discharge summaries, pharmacy invoices, and garage repair estimates arrive in mixed PDF formats.',
          'Adjusters manually cross-reference 50+ page claim dossiers against dense policy booklets.',
          'Critical timeline gaps and conflicting dates go unnoticed under heavy caseloads.',
        ],
      },
      solution: {
        heading: 'Contextual Ingestion & RRF Fusion',
        points: [
          'Automatic text & OCR extraction with 500-character chunking and 100-character overlap.',
          'Dual retrieval via PostgreSQL pgvector (384-dim dense) and tsvector lexical search fused with Reciprocal Rank Fusion.',
          'Chronological clinical & incident timeline generated with verified evidence provenance.',
        ],
      },
    },
    {
      id: 'hallucinations',
      title: 'AI Hallucinations & Fabrications',
      challenge: {
        heading: 'Invented Clauses & Fake Quotes',
        points: [
          'Generic LLMs hallucinate non-existent sub-limits, deductibles, or medical diagnoses.',
          'Unanchored summary points cannot be verified back to an authentic page or document.',
          'Audit teams cannot defend AI-generated claims assessments in regulatory inquiries.',
        ],
      },
      solution: {
        heading: 'Deterministic Verbatim Grounding',
        points: [
          'Every single finding is bound to a canonical chunk_id with an exact verbatim source substring.',
          'RFC 6901 JSON pointer paths deep-link findings directly to specific claim fields.',
          'Findings failing exact substring validation are rejected before state persistence.',
        ],
      },
    },
    {
      id: 'liability',
      title: 'Adjudication & Legal Liability',
      challenge: {
        heading: 'Black-Box Autonomous Denials',
        points: [
          'Unconstrained models making definitive coverage denials create severe bad-faith exposure.',
          'Claimants subjected to automated rejection algorithms without explanation rights.',
          'Lack of transparent adjuster sign-off breaks compliance and insurance regulations.',
        ],
      },
      solution: {
        heading: 'Strict Assistive Human-in-the-Loop',
        points: [
          'Strict architectural boundary: ClaimSage assists investigators and NEVER settles claims.',
          'AI models are programmatically prohibited from emitting definitive fraud or denial verdicts.',
          'Human review queue requires licensed adjuster sign-off and records audit trails.',
        ],
      },
    },
    {
      id: 'resilience',
      title: 'System Fragility & Token Limits',
      challenge: {
        heading: 'API 429 Crashes & Silent Truncations',
        points: [
          'Disparate records exceed context limits, causing silent truncation of vital policy exclusions.',
          'Downstream workflows crash completely when external cloud LLMs encounter HTTP 429 rate limits.',
          'Investigations must be re-run from scratch, wasting time and API costs.',
        ],
      },
      solution: {
        heading: 'Token Budgeting & Deterministic Fallback',
        points: [
          'TokenBudgetManager calculates pre-invocation token allocations for each specialist.',
          'Deterministic Fallback Mode aggregates upstream specialist findings if cloud LLMs rate limit.',
          'Zero hallucinated findings added during fallback; reports are marked partial for human review.',
        ],
      },
    },
  ]

  const fallback = comparisons[0]!
  const current = comparisons[activeTab] ?? fallback

  return (
    <section id="product" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
            Precision Over Guesswork
          </p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
            Why traditional investigation breaks down — and how ClaimSage fixes it.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
            Claims adjusters cannot afford probabilistic guesswork. ClaimSage replaces brittle black-box chats with a verifiable, multi-agent investigation architecture.
          </p>
        </div>

        {/* Tab Buttons */}
        <div className="mt-10 flex flex-wrap gap-2 border-b border-[#E9E5DB] pb-4">
          {comparisons.map((item, idx) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveTab(idx)}
              className={`rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
                activeTab === idx
                  ? 'bg-[#183F32] text-white shadow-sm'
                  : 'bg-white text-[#6F7770] hover:bg-[#FAF9F6] hover:text-[#18211D] border border-[#E9E5DB]'
              }`}
            >
              {item.title}
            </button>
          ))}
        </div>

        {/* Interactive Side-by-Side Comparison Grid */}
        <div className="mt-8 grid gap-6 lg:grid-cols-2">
          {/* Challenge Card */}
          <div className="flex flex-col justify-between rounded-3xl border border-[#E9E5DB] bg-white p-6 sm:p-8 shadow-xs">
            <div>
              <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                <span className="inline-flex items-center gap-2 rounded-full border border-[#EDE7D9] bg-[#FAF9F6] px-3 py-1 text-xs font-semibold text-[#6F7770]">
                  <XCircle className="size-4 text-[#B79B6A]" />
                  <span>The Legacy Reality</span>
                </span>
                <span className="text-xs text-[#6F7770]">Friction Point #{activeTab + 1}</span>
              </div>

              <h3 className="mt-6 font-display text-xl font-semibold text-[#18211D]">
                {current.challenge.heading}
              </h3>

              <ul className="mt-6 space-y-4">
                {current.challenge.points.map((pt) => (
                  <li key={pt} className="flex items-start gap-3 text-sm leading-relaxed text-[#6F7770]">
                    <span className="mt-1 grid size-5 shrink-0 place-items-center rounded-full bg-[#EDE7D9] text-[#6F7770]">
                      ×
                    </span>
                    <span>{pt}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="mt-8 rounded-2xl bg-[#FAF9F6] p-4 border border-[#E9E5DB] text-xs text-[#6F7770]">
              <span className="font-semibold text-[#18211D]">Outcome:</span> Slow investigation cycles, adjuster fatigue, and unmitigated litigation risk.
            </div>
          </div>

          {/* Solution Card */}
          <div className="flex flex-col justify-between rounded-3xl border border-[#397454]/30 bg-white p-6 sm:p-8 shadow-[0_12px_32px_-16px_rgba(24,63,50,0.12)] ring-1 ring-[#183F32]/10">
            <div>
              <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                <span className="inline-flex items-center gap-2 rounded-full border border-[#DDE9DF] bg-[#DDE9DF]/50 px-3 py-1 text-xs font-semibold text-[#183F32]">
                  <CheckCircle2 className="size-4 text-[#397454]" />
                  <span>The ClaimSage Standard</span>
                </span>
                <span className="text-xs font-semibold text-[#397454]">Verifiable System</span>
              </div>

              <h3 className="mt-6 font-display text-xl font-semibold text-[#18211D]">
                {current.solution.heading}
              </h3>

              <ul className="mt-6 space-y-4">
                {current.solution.points.map((pt) => (
                  <li key={pt} className="flex items-start gap-3 text-sm leading-relaxed text-[#18211D]">
                    <span className="mt-1 grid size-5 shrink-0 place-items-center rounded-full bg-[#DDE9DF] text-[#183F32]">
                      ✓
                    </span>
                    <span>{pt}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="mt-8 rounded-2xl bg-[#DDE9DF]/30 p-4 border border-[#DDE9DF] text-xs text-[#183F32]">
              <span className="font-semibold">Outcome:</span> Complete auditability, guaranteed quote citations, and zero black-box denials.
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

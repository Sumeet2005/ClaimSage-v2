import {
  Network,
  Search,
  FileCheck,
  UserCheck,
  ShieldCheck,
  ArrowUpRight,
} from 'lucide-react'

export function CapabilityStrip() {
  const capabilities = [
    {
      title: 'Multi-Agent Orchestration',
      metric: '6 Specialists',
      description: 'LangGraph state engine with deterministic routing & pre-invocation token budgeting.',
      icon: Network,
      anchor: '#agents',
    },
    {
      title: 'Contextual Hybrid RAG',
      metric: 'pgvector + BM25',
      description: 'Dense 384-dim semantic embeddings combined with lexical inverted index via RRF.',
      icon: Search,
      anchor: '#rag',
    },
    {
      title: 'Evidence Traceability',
      metric: '100% Verbatim',
      description: 'Every observation bound to an immutable chunk_id with exact source substring validation.',
      icon: FileCheck,
      anchor: '#product',
    },
    {
      title: 'Human-in-the-Loop',
      metric: 'Mandatory Sign-off',
      description: 'Strict decision boundaries: zero autonomous approvals, denials, or claim payments.',
      icon: UserCheck,
      anchor: '#security',
    },
    {
      title: 'Auditable Investigations',
      metric: 'RFC 6901 Pointers',
      description: 'Append-only audit ledger tracking every prompt reservation, calculation, and adjuster override.',
      icon: ShieldCheck,
      anchor: '#security',
    },
  ]

  return (
    <section className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-8">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {capabilities.map((cap) => {
            const Icon = cap.icon
            return (
              <a
                key={cap.title}
                href={cap.anchor}
                className="group relative flex flex-col justify-between rounded-2xl border border-[#E9E5DB] bg-white p-4 transition-all duration-200 hover:-translate-y-0.5 hover:border-[#183F32]/30 hover:shadow-sm"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="grid size-9 place-items-center rounded-xl bg-[#FAF9F6] text-[#183F32] group-hover:bg-[#DDE9DF] transition-colors">
                      <Icon className="size-4.5" />
                    </span>
                    <span className="rounded-md bg-[#FAF9F6] px-2 py-0.5 text-[10px] font-semibold tracking-wide text-[#397454] border border-[#E9E5DB]/70">
                      {cap.metric}
                    </span>
                  </div>

                  <h3 className="mt-3 font-display text-sm font-semibold text-[#18211D]">
                    {cap.title}
                  </h3>
                  <p className="mt-1 text-xs leading-relaxed text-[#6F7770]">
                    {cap.description}
                  </p>
                </div>

                <div className="mt-4 flex items-center gap-1 text-[11px] font-semibold text-[#183F32] opacity-80 group-hover:opacity-100">
                  <span>Explore capability</span>
                  <ArrowUpRight className="size-3 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </div>
              </a>
            )
          })}
        </div>
      </div>
    </section>
  )
}

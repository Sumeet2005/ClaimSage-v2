import { useState } from 'react'
import {
  Search,
  Database,
  FileCheck2,
  Cpu,
  Sparkles,
  GitMerge,
  Quote,
  ShieldCheck,
} from 'lucide-react'
import { RAG_PRESETS } from '../data/rag-data'

export function RagIntelligenceSection() {
  const [selectedPresetId, setSelectedPresetId] = useState<string>('room-rent')

  const fallbackPreset = RAG_PRESETS[0]!
  const currentPreset =
    RAG_PRESETS.find((p) => p.id === selectedPresetId) ?? fallbackPreset

  const pipelineStages = [
    {
      step: '01',
      title: 'Ingestion & Chunking',
      tech: '500 chars / 100 overlap',
      description: 'PDFs and medical bills are extracted via native OCR and segmented into sliding character windows preserving sentence boundaries.',
      icon: Database,
    },
    {
      step: '02',
      title: 'Dense Vectors',
      tech: 'all-MiniLM-L6-v2 (384-dim)',
      description: 'Local CPU SIMD embedding models generate dense representations stored in PostgreSQL pgvector columns with HNSW cosine indexes.',
      icon: Cpu,
    },
    {
      step: '03',
      title: 'Sparse Inverted Index',
      tech: 'PostgreSQL tsvector & GIN',
      description: 'Lexical full-text queries run concurrently using ts_rank_cd to capture exact policy clause codes and ICD-10 medical terminology.',
      icon: Search,
    },
    {
      step: '04',
      title: 'Reciprocal Rank Fusion',
      tech: 'RRF with k = 60',
      description: 'Dense semantic rank and sparse keyword rank are fused mathematically, eliminating single-retriever blindspots.',
      icon: GitMerge,
    },
    {
      step: '05',
      title: 'Verbatim Anchoring',
      tech: '100% Quote Matching',
      description: 'Retrieved canonical chunks are checked for exact substring provenance before downstream specialist ingestion.',
      icon: FileCheck2,
    },
  ]

  return (
    <section id="rag" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
            Contextual Hybrid Retrieval
          </p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
            Evidence intelligence powered by pgvector and Reciprocal Rank Fusion.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
            Pure semantic vector search often misses technical clause identifiers, while pure keyword search misses paraphrased medical symptoms. ClaimSage fuses both with mathematical rigor.
          </p>
        </div>

        {/* 5 Pipeline Stages */}
        <div className="mt-12 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          {pipelineStages.map((stage) => {
            const Icon = stage.icon
            return (
              <div
                key={stage.step}
                className="flex flex-col justify-between rounded-2xl border border-[#E9E5DB] bg-white p-5 shadow-2xs"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="font-mono text-xs font-bold text-[#397454]">
                      {stage.step}
                    </span>
                    <span className="grid size-8 place-items-center rounded-lg bg-[#FAF9F6] text-[#183F32] border border-[#E9E5DB]">
                      <Icon className="size-4" />
                    </span>
                  </div>

                  <h3 className="mt-4 font-display text-base font-semibold text-[#18211D]">
                    {stage.title}
                  </h3>
                  <code className="mt-1 block font-mono text-[11px] text-[#397454]">
                    {stage.tech}
                  </code>
                  <p className="mt-2 text-xs leading-relaxed text-[#6F7770]">
                    {stage.description}
                  </p>
                </div>
              </div>
            )
          })}
        </div>

        {/* Interactive Query Simulator Sandbox */}
        <div className="mt-12 rounded-3xl border border-[#E9E5DB] bg-white p-6 sm:p-8 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#E9E5DB] pb-6">
            <div>
              <span className="inline-flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-[#397454]">
                <Sparkles className="size-3.5" />
                <span>Interactive RRF Sandbox</span>
              </span>
              <h3 className="mt-1 font-display text-xl font-semibold text-[#18211D]">
                Test Reciprocal Rank Fusion on Live Policy Queries
              </h3>
            </div>

            {/* Presets */}
            <div className="flex flex-wrap gap-2">
              {RAG_PRESETS.map((preset) => (
                <button
                  key={preset.id}
                  type="button"
                  onClick={() => setSelectedPresetId(preset.id)}
                  className={`rounded-xl px-3 py-1.5 text-xs font-medium transition-colors border ${
                    selectedPresetId === preset.id
                      ? 'border-[#183F32] bg-[#183F32] text-white shadow-2xs'
                      : 'border-[#E9E5DB] bg-[#FAF9F6] text-[#6F7770] hover:text-[#18211D]'
                  }`}
                >
                  {preset.label}
                </button>
              ))}
            </div>
          </div>

          {/* Active Query Display */}
          <div className="mt-6 rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-4 text-xs">
            <span className="text-[#6F7770] uppercase font-semibold">Specialist Query:</span>
            <p className="mt-1 font-display text-sm font-semibold text-[#18211D]">
              {`"`}{currentPreset.queryText}{`"`}
            </p>
          </div>

          {/* Dual Ranks to Fused Result Grid */}
          <div className="mt-6 grid gap-6 lg:grid-cols-3 items-stretch">
            {/* Dense Vector Match */}
            <div className="rounded-2xl border border-[#E9E5DB] bg-white p-5 flex flex-col justify-between shadow-2xs">
              <div>
                <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-3 text-xs">
                  <span className="font-semibold text-[#18211D]">Dense Vector Search</span>
                  <span className="rounded bg-[#DDE9DF] px-2 py-0.5 font-mono text-[10px] font-bold text-[#183F32]">
                    Cosine Similarity: {currentPreset.denseTopMatch.similarity}
                  </span>
                </div>
                <div className="mt-3 text-xs text-[#6F7770] space-y-1">
                  <p>Chunk: <code className="text-[#183F32]">{currentPreset.denseTopMatch.chunkId}</code></p>
                  <p>Document: {currentPreset.denseTopMatch.sourceDoc} (p.{currentPreset.denseTopMatch.page})</p>
                  <p className="font-semibold text-[#397454]">Rank: #{currentPreset.denseTopMatch.rank}</p>
                </div>
                <p className="mt-3 rounded-xl bg-[#FAF9F6] p-3 text-xs leading-relaxed text-[#18211D] border border-[#E9E5DB]">
                  {currentPreset.denseTopMatch.snippet}
                </p>
              </div>
            </div>

            {/* Sparse BM25 Match */}
            <div className="rounded-2xl border border-[#E9E5DB] bg-white p-5 flex flex-col justify-between shadow-2xs">
              <div>
                <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-3 text-xs">
                  <span className="font-semibold text-[#18211D]">Sparse Lexical Search</span>
                  <span className="rounded bg-[#EDE7D9] px-2 py-0.5 font-mono text-[10px] font-bold text-[#18211D]">
                    ts_rank_cd: {currentPreset.sparseTopMatch.tsRankScore}
                  </span>
                </div>
                <div className="mt-3 text-xs text-[#6F7770] space-y-1">
                  <p>Chunk: <code className="text-[#18211D]">{currentPreset.sparseTopMatch.chunkId}</code></p>
                  <p>Document: {currentPreset.sparseTopMatch.sourceDoc} (p.{currentPreset.sparseTopMatch.page})</p>
                  <p className="font-semibold text-[#397454]">Rank: #{currentPreset.sparseTopMatch.rank}</p>
                </div>
                <p className="mt-3 rounded-xl bg-[#FAF9F6] p-3 text-xs leading-relaxed text-[#18211D] border border-[#E9E5DB]">
                  {currentPreset.sparseTopMatch.snippet}
                </p>
              </div>
            </div>

            {/* Fused Canonical Result */}
            <div className="rounded-2xl border border-[#397454]/40 bg-[#FAF9F6] p-5 flex flex-col justify-between shadow-sm ring-1 ring-[#183F32]/10">
              <div>
                <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-3 text-xs">
                  <span className="font-semibold text-[#183F32]">Fused Canonical Result</span>
                  <span className="rounded bg-[#183F32] px-2 py-0.5 font-mono text-[10px] font-bold text-white">
                    RRF Score: {currentPreset.fusedTopResult.rrfScore}
                  </span>
                </div>

                <div className="mt-3 text-xs text-[#183F32] space-y-1 font-medium">
                  <p>{currentPreset.fusedTopResult.clauseRef}</p>
                  <p className="text-[11px] text-[#6F7770]">Source: {currentPreset.fusedTopResult.sourceDoc}</p>
                </div>

                <div className="mt-3 rounded-xl bg-white p-3.5 border border-[#E9E5DB] text-xs leading-relaxed text-[#18211D]">
                  <Quote className="size-3 text-[#397454] mb-1" />
                  <span className="font-medium">{currentPreset.fusedTopResult.verbatimQuote}</span>
                </div>
              </div>

              <div className="mt-4 flex items-center gap-1.5 text-[11px] text-[#397454] font-semibold">
                <ShieldCheck className="size-3.5" />
                <span>100% Verbatim Verified Substring</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

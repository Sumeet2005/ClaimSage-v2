import { useState } from 'react'
import {
  BriefcaseBusiness,
  FileText,
  ShieldCheck,
  Activity,
  Layers,
  FileCheck2,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export function ProductShowcaseSection() {
  const [activeTab, setActiveTab] = useState<
    'dashboard' | 'claim_detail' | 'investigation' | 'evidence' | 'human_review'
  >('dashboard')

  return (
    <section id="product-preview" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
              Interface & Experience
            </p>
            <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
              Inside the ClaimSage workspace.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
              Built with warm ivory tones, deep forest accents, and tactile enterprise ergonomics. Explore the live interactive modules adjusters use every day.
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-[#6F7770]">Design reference:</span>
            <span className="rounded-lg border border-[#E9E5DB] bg-white px-2.5 py-1 text-xs font-semibold text-[#183F32]">
              Warm Ivory + Forest Green
            </span>
          </div>
        </div>

        {/* Tab Switcher */}
        <div className="mt-10 flex flex-wrap gap-2 border-b border-[#E9E5DB] pb-4">
          <button
            type="button"
            onClick={() => setActiveTab('dashboard')}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeTab === 'dashboard'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            <BriefcaseBusiness className="size-3.5" />
            <span>Claims Dashboard</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('claim_detail')}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeTab === 'claim_detail'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            <FileText className="size-3.5" />
            <span>Claim Details</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('investigation')}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeTab === 'investigation'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            <Activity className="size-3.5" />
            <span>Investigation Execution</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('evidence')}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeTab === 'evidence'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            <Layers className="size-3.5" />
            <span>Evidence Citations</span>
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('human_review')}
            className={`flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-semibold transition-all ${
              activeTab === 'human_review'
                ? 'bg-[#183F32] text-white shadow-xs'
                : 'bg-white text-[#6F7770] hover:text-[#18211D] border border-[#E9E5DB]'
            }`}
          >
            <ShieldCheck className="size-3.5" />
            <span>Human Review Queue</span>
          </button>
        </div>

        {/* Realistic App Frame Simulation */}
        <div className="mt-8 overflow-hidden rounded-3xl border border-[#E9E5DB] bg-white shadow-[0_24px_64px_-32px_rgba(24,63,50,0.18)]">
          {/* Mock Browser Topbar */}
          <div className="flex items-center justify-between border-b border-[#E9E5DB] bg-[#FAF9F6] px-4 py-3 sm:px-6">
            <div className="flex items-center gap-2">
              <span className="size-3 rounded-full bg-[#E9E5DB]" />
              <span className="size-3 rounded-full bg-[#E9E5DB]" />
              <span className="size-3 rounded-full bg-[#E9E5DB]" />
              <span className="ml-3 hidden text-[11px] font-mono text-[#6F7770] sm:inline-block">
                app.claimsage.internal / {activeTab.replace('_', '-')}
              </span>
            </div>

            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-white px-2.5 py-0.5 text-[10px] font-medium text-[#183F32] border border-[#E9E5DB]">
                <span className="size-1.5 rounded-full bg-[#397454]" />
                Authenticated Session
              </span>
            </div>
          </div>

          {/* Interactive Screen Container */}
          <div className="grid lg:grid-cols-[240px_1fr] min-h-[520px]">
            {/* Sidebar Simulation */}
            <div className="hidden lg:flex flex-col justify-between bg-[#191C19] p-4 text-[#FBFBF6]">
              <div>
                <div className="flex items-center gap-2.5 px-2 py-2">
                  <span className="grid size-8 place-items-center rounded-xl bg-[#397454] text-white shadow-xs">
                    <ShieldCheck className="size-4.5" strokeWidth={1.8} />
                  </span>
                  <span className="font-display text-base font-semibold tracking-tight text-white">
                    ClaimSage
                  </span>
                </div>

                <div className="mt-6 space-y-1 text-xs">
                  <p className="px-2 text-[10px] font-semibold text-[#7C8579] uppercase tracking-wider">
                    Workspace
                  </p>
                  <div
                    className={`flex items-center gap-2.5 rounded-xl px-2.5 py-2 font-medium transition-colors ${
                      activeTab === 'dashboard'
                        ? 'bg-white/10 text-white font-semibold'
                        : 'text-[#A0A79D] hover:bg-white/5'
                    }`}
                  >
                    <BriefcaseBusiness className="size-4" />
                    <span>Dashboard</span>
                  </div>
                  <div
                    className={`flex items-center gap-2.5 rounded-xl px-2.5 py-2 font-medium transition-colors ${
                      activeTab === 'claim_detail'
                        ? 'bg-white/10 text-white font-semibold'
                        : 'text-[#A0A79D] hover:bg-white/5'
                    }`}
                  >
                    <FileText className="size-4" />
                    <span>Claims</span>
                  </div>
                  <div
                    className={`flex items-center gap-2.5 rounded-xl px-2.5 py-2 font-medium transition-colors ${
                      activeTab === 'investigation' || activeTab === 'evidence'
                        ? 'bg-white/10 text-white font-semibold'
                        : 'text-[#A0A79D] hover:bg-white/5'
                    }`}
                  >
                    <Activity className="size-4" />
                    <span>Investigations</span>
                  </div>
                  <div
                    className={`flex items-center gap-2.5 rounded-xl px-2.5 py-2 font-medium transition-colors ${
                      activeTab === 'human_review'
                        ? 'bg-white/10 text-white font-semibold'
                        : 'text-[#A0A79D] hover:bg-white/5'
                    }`}
                  >
                    <FileCheck2 className="size-4" />
                    <span>Review Queue</span>
                  </div>
                </div>
              </div>

              <div className="border-t border-white/10 pt-3 text-[11px] text-[#7C8579]">
                <div className="flex items-center gap-2 px-2">
                  <div className="grid size-6 place-items-center rounded-full bg-[#397454] text-white font-bold text-[10px]">
                    SA
                  </div>
                  <div className="truncate">
                    <p className="font-medium text-white truncate">Sumeet Adjuster</p>
                    <p className="text-[10px] text-[#A0A79D]">Claims Analyst</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Main Stage View depending on activeTab */}
            <div className="bg-[#FAF9F6] p-6 sm:p-8">
              {activeTab === 'dashboard' && (
                <div>
                  <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                    <div>
                      <p className="text-[10px] font-semibold text-[#397454] uppercase tracking-wider">
                        Investigation workspace
                      </p>
                      <h3 className="mt-1 font-display text-2xl font-semibold text-[#18211D]">
                        Your claims, in context.
                      </h3>
                      <p className="text-xs text-[#6F7770]">
                        A considered view of the claims and reviews available to your account.
                      </p>
                    </div>
                    <Button size="sm" className="bg-[#DDE9DF] text-[#183F32] hover:bg-[#DDE9DF]/80 text-xs font-semibold">
                      Open claims
                    </Button>
                  </div>

                  {/* 3 Metric Cards matching dashboard-page.tsx */}
                  <div className="mt-6 grid gap-4 sm:grid-cols-3">
                    <div className="rounded-2xl border border-[#E9E5DB] bg-white p-4 shadow-2xs">
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="text-xs font-medium text-[#6F7770]">Claims available</p>
                          <p className="mt-2 font-display text-3xl font-medium tracking-tight text-[#18211D]">
                            12
                          </p>
                          <p className="mt-1 text-[11px] text-[#6F7770]">
                            Claims you are authorized to access
                          </p>
                        </div>
                        <span className="grid size-9 place-items-center rounded-xl bg-[#DDE9DF] text-[#183F32]">
                          <BriefcaseBusiness className="size-4" />
                        </span>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-[#E9E5DB] bg-white p-4 shadow-2xs">
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="text-xs font-medium text-[#6F7770]">Motor claims</p>
                          <p className="mt-2 font-display text-3xl font-medium tracking-tight text-[#18211D]">
                            7
                          </p>
                          <p className="mt-1 text-[11px] text-[#6F7770]">
                            Auto and motor insurance
                          </p>
                        </div>
                        <span className="grid size-9 place-items-center rounded-xl bg-[#EDE7D9] text-[#18211D]">
                          <FileText className="size-4" />
                        </span>
                      </div>
                    </div>

                    <div className="rounded-2xl border border-[#E9E5DB] bg-white p-4 shadow-2xs">
                      <div className="flex items-start justify-between">
                        <div>
                          <p className="text-xs font-medium text-[#6F7770]">Health claims</p>
                          <p className="mt-2 font-display text-3xl font-medium tracking-tight text-[#18211D]">
                            5
                          </p>
                          <p className="mt-1 text-[11px] text-[#6F7770]">Health insurance</p>
                        </div>
                        <span className="grid size-9 place-items-center rounded-xl bg-[#F3F0E7] text-[#18211D]">
                          <ShieldCheck className="size-4" />
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Recent Claims Table */}
                  <div className="mt-6 rounded-2xl border border-[#E9E5DB] bg-white p-4 shadow-2xs">
                    <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-3">
                      <h4 className="font-display text-sm font-semibold text-[#18211D]">
                        Recent claims
                      </h4>
                      <span className="text-xs text-[#397454] font-medium">View all</span>
                    </div>

                    <div className="mt-3 divide-y divide-[#E9E5DB] text-xs">
                      {[
                        {
                          id: 'CLM-2026-9921',
                          type: 'Motor',
                          policy: 'POL-AUTO-8812',
                          date: 'Nov 04, 2026',
                          status: 'ready_for_review',
                          statusTone: 'bg-[#DDE9DF] text-[#183F32]',
                        },
                        {
                          id: 'CLM-2026-8839',
                          type: 'Health',
                          policy: 'POL-HLTH-4491',
                          date: 'Nov 02, 2026',
                          status: 'investigating',
                          statusTone: 'bg-[#EDE7D9] text-[#18211D]',
                        },
                        {
                          id: 'CLM-2026-7714',
                          type: 'Motor',
                          policy: 'POL-AUTO-3319',
                          date: 'Oct 29, 2026',
                          status: 'completed',
                          statusTone: 'bg-[#DDE9DF] text-[#183F32]',
                        },
                      ].map((row) => (
                        <div key={row.id} className="flex items-center justify-between py-2.5">
                          <div className="flex items-center gap-3">
                            <span className="font-mono font-medium text-[#18211D]">{row.id}</span>
                            <span className="rounded bg-[#FAF9F6] px-1.5 py-0.5 text-[10px] text-[#6F7770] border border-[#E9E5DB]">
                              {row.type}
                            </span>
                            <span className="hidden sm:inline text-[#6F7770] font-mono text-[11px]">
                              {row.policy}
                            </span>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-[#6F7770] text-[11px]">{row.date}</span>
                            <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${row.statusTone}`}>
                              {row.status.replace('_', ' ')}
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'claim_detail' && (
                <div>
                  <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                    <div>
                      <span className="font-mono text-xs text-[#397454]">Claim #CLM-2026-8839</span>
                      <h3 className="mt-1 font-display text-2xl font-semibold text-[#18211D]">
                        Hospitalization Claim Dossier
                      </h3>
                      <p className="text-xs text-[#6F7770]">
                        Assigned Adjuster: Sumeet · Apollo Hospitals, Bengaluru · Total Claimed: ₹145,000
                      </p>
                    </div>
                    <Badge variant="default" className="bg-[#DDE9DF] text-[#183F32] font-semibold">
                      Under Investigation
                    </Badge>
                  </div>

                  <div className="mt-6 grid gap-4 sm:grid-cols-2">
                    <div className="rounded-2xl border border-[#E9E5DB] bg-white p-4">
                      <p className="text-xs font-semibold text-[#6F7770] uppercase">
                        Associated Policy
                      </p>
                      <p className="mt-2 text-sm font-semibold text-[#18211D]">
                        ClaimSage Synthetic Health Policy v3
                      </p>
                      <p className="mt-1 text-xs text-[#6F7770]">
                        Sum Insured: ₹500,000 · Room Rent Capping: 1% SI / day
                      </p>
                    </div>

                    <div className="rounded-2xl border border-[#E9E5DB] bg-white p-4">
                      <p className="text-xs font-semibold text-[#6F7770] uppercase">
                        Indexed Documents (3 Files)
                      </p>
                      <p className="mt-2 text-sm font-semibold text-[#18211D]">
                        Discharge_Summary.pdf, Final_Bill.pdf
                      </p>
                      <p className="mt-1 text-xs text-[#397454]">
                        ✓ SHA-256 Verified in MinIO Storage
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'investigation' && (
                <div>
                  <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                    <div>
                      <p className="text-[10px] font-semibold text-[#397454] uppercase tracking-wider">
                        LangGraph Execution Monitor
                      </p>
                      <h3 className="mt-1 font-display text-2xl font-semibold text-[#18211D]">
                        Active Multi-Agent Orchestration
                      </h3>
                      <p className="text-xs text-[#6F7770]">
                        Claim CLM-2026-8839 · Primary LLM: Groq Cloud (gpt-oss-120b)
                      </p>
                    </div>
                    <span className="flex items-center gap-1.5 rounded-full bg-[#DDE9DF] px-3 py-1 text-xs font-semibold text-[#183F32]">
                      <span className="size-2 animate-ping rounded-full bg-[#397454]" />
                      Specialist Active
                    </span>
                  </div>

                  <div className="mt-6 space-y-3">
                    {[
                      { name: 'Supervisor Agent', status: 'Completed (Plan formulated)', time: '0.4s' },
                      { name: 'Intake Agent', status: 'Completed (3 docs indexed)', time: '1.1s' },
                      { name: 'Evidence Analyst', status: 'Completed (7 timeline facts extracted)', time: '1.8s' },
                      { name: 'Policy Analyst', status: 'Completed (Room rent clause evaluated)', time: '1.4s' },
                      { name: 'Risk & Anomaly Agent', status: 'Active (Reconciling duplicate billing code)', time: 'Executing…' },
                    ].map((st, i) => (
                      <div
                        key={st.name}
                        className="flex items-center justify-between rounded-xl border border-[#E9E5DB] bg-white p-3 text-xs"
                      >
                        <div className="flex items-center gap-2.5">
                          <span className="grid size-6 place-items-center rounded-lg bg-[#FAF9F6] text-[#183F32] font-mono text-[10px] font-bold">
                            0{i + 1}
                          </span>
                          <span className="font-semibold text-[#18211D]">{st.name}</span>
                          <span className="text-[#6F7770]">{st.status}</span>
                        </div>
                        <span className="font-mono text-[#397454]">{st.time}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {activeTab === 'evidence' && (
                <div>
                  <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                    <div>
                      <p className="text-[10px] font-semibold text-[#397454] uppercase tracking-wider">
                        Verbatim Citations & Provenance
                      </p>
                      <h3 className="mt-1 font-display text-2xl font-semibold text-[#18211D]">
                        Evidence Anchoring Explorer
                      </h3>
                      <p className="text-xs text-[#6F7770]">
                        Every observation has an immutable chunk_id and exact source substring.
                      </p>
                    </div>
                    <Badge variant="outline" className="border-[#397454] text-[#397454] text-xs">
                      100% Quote Match Verified
                    </Badge>
                  </div>

                  <div className="mt-6 rounded-2xl border border-[#E9E5DB] bg-white p-5">
                    <div className="flex items-center justify-between text-xs text-[#6F7770]">
                      <span className="font-mono text-[#183F32] font-semibold">
                        chunk_id: doc-chk-8839-a2 · Page 2
                      </span>
                      <span>Discharge_Summary.pdf</span>
                    </div>

                    <div className="mt-3 rounded-xl bg-[#FAF9F6] p-4 border border-[#E9E5DB] text-xs leading-relaxed text-[#18211D] font-mono">
                      <span className="font-bold text-[#397454]">{`"`}</span>
                      Patient shifted to ICU 402 at 14:15 hrs post operative vitals stable. Stayed in ICU until 14/10/2026 09:00 hrs prior to room transfer.
                      <span className="font-bold text-[#397454]">{`"`}</span>
                    </div>

                    <div className="mt-4 flex items-center justify-between text-xs text-[#6F7770]">
                      <span>RFC 6901 Pointer: <code className="text-[#397454]">/timeline/0/evidence_id</code></span>
                      <span className="text-[#183F32] font-semibold">PostgreSQL pgvector Cosine Rank #1</span>
                    </div>
                  </div>
                </div>
              )}

              {activeTab === 'human_review' && (
                <div>
                  <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                    <div>
                      <p className="text-[10px] font-semibold text-[#397454] uppercase tracking-wider">
                        Human-in-the-Loop Sign-off
                      </p>
                      <h3 className="mt-1 font-display text-2xl font-semibold text-[#18211D]">
                        Adjuster Determination Panel
                      </h3>
                      <p className="text-xs text-[#6F7770]">
                        ClaimSage assists investigators. It does NOT autonomously approve or pay claims.
                      </p>
                    </div>
                    <Badge className="bg-[#EDE7D9] text-[#18211D] border-none font-semibold">
                      Human Review Mandatory
                    </Badge>
                  </div>

                  <div className="mt-6 rounded-2xl border border-[#E9E5DB] bg-white p-5">
                    <p className="text-xs font-semibold text-[#18211D]">
                      Synthesized Finding for Review:
                    </p>
                    <p className="mt-1 text-xs text-[#6F7770] leading-relaxed">
                      Laparoscopic cholecystectomy treatment covered under Section 2.1. Room rent capping deduction applied to 2 ICU days (₹10,000 deduction). Unbundled USG scan flagged for verification.
                    </p>

                    <div className="mt-6 flex flex-wrap gap-2 pt-4 border-t border-[#E9E5DB]">
                      <Button size="sm" className="bg-[#183F32] text-white hover:bg-[#245744] text-xs font-semibold">
                        Approve & Record Audit Stamp
                      </Button>
                      <Button size="sm" variant="outline" className="border-[#E9E5DB] text-xs">
                        Flag for Follow-up
                      </Button>
                      <Button size="sm" variant="ghost" className="text-xs text-[#6F7770]">
                        Override Specialist Finding
                      </Button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

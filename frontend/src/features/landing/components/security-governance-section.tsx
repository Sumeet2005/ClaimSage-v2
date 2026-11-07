import {
  ShieldCheck,
  UserCheck,
  Lock,
  History,
  FileCheck2,
  Mail,
} from 'lucide-react'

export function SecurityGovernanceSection() {
  const securityPillars = [
    {
      title: 'Role-Based Access Control (RBAC)',
      description:
        'Granular role segregation across Claims Adjusters, Policy Specialists, and Workspace Administrators. Session tokens are held strictly in memory with zero localStorage leakage.',
      icon: Lock,
      badge: 'Argon2 / Bcrypt Sessions',
    },
    {
      title: 'Append-Only Audit Trails',
      description:
        'Every agent invocation, prompt token reservation, parameter change, and adjuster sign-off is permanently recorded in the immutable audit_events database table.',
      icon: History,
      badge: 'audit_events Table',
    },
    {
      title: 'Complete Evidence Traceability',
      description:
        'Every single fact in an investigation report carries an immutable chunk_id, page index, and RFC 6901 JSON pointer. Zero ungrounded observations are permitted.',
      icon: FileCheck2,
      badge: '100% Provenance Anchored',
    },
    {
      title: 'Mandatory Human Review',
      description:
        'Adjusters inspect generated findings, evaluate conflicting statements, modify line items, and attach licensed sign-off signatures before any claim determination.',
      icon: UserCheck,
      badge: 'Investigator in Control',
    },
    {
      title: 'Cryptographic Object Storage',
      description:
        'Claim PDFs, medical records, and policy documents are stored as immutable binary objects in MinIO S3 with SHA-256 integrity hashes verified on retrieval.',
      icon: ShieldCheck,
      badge: 'SHA-256 Hash Verification',
    },
    {
      title: 'Sandboxed Email Outbox',
      description:
        'Automated follow-up drafts and claimant communications are quarantined in a durable relational database outbox, preventing unintended external dispatch.',
      icon: Mail,
      badge: 'Durable Outbox Queue',
    },
  ]

  return (
    <section id="security" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Mandatory Assistive Statement Banner */}
        <div className="rounded-3xl border border-[#183F32]/20 bg-[#183F32] p-6 sm:p-10 text-white shadow-md">
          <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-6">
            <div className="max-w-3xl">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-widest text-[#EDE7D9]">
                <ShieldCheck className="size-4 text-[#DDE9DF]" />
                <span>Foundational Governance Principle</span>
              </div>
              <h3 className="mt-3 font-display text-2xl font-semibold leading-snug sm:text-3xl text-white">
                ClaimSage is an assistive copilot. It does not autonomously approve, reject, settle, or pay claims.
              </h3>
              <p className="mt-3 text-sm leading-relaxed text-[#DDE9DF]">
                The platform empowers human investigators by automating document synthesis and clause retrieval while leaving all legal, coverage, and financial determinations exclusively with authorized personnel.
              </p>
            </div>

            <div className="rounded-2xl border border-white/20 bg-white/10 p-4 text-center text-xs backdrop-blur-xs">
              <p className="font-semibold text-white">Full Regulatory Alignment</p>
              <p className="mt-1 text-[#DDE9DF]">Auditable • Transparent • Explainable</p>
            </div>
          </div>
        </div>

        {/* Section Header */}
        <div className="mt-16 max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
            Enterprise Governance
          </p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
            Security and auditability built into every layer.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
            Designed from day one for institutional compliance, data isolation, and defensible audit readiness.
          </p>
        </div>

        {/* Security Grid */}
        <div className="mt-10 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
          {securityPillars.map((p) => {
            const Icon = p.icon
            return (
              <div
                key={p.title}
                className="flex flex-col justify-between rounded-2xl border border-[#E9E5DB] bg-white p-6 shadow-2xs transition-all hover:border-[#183F32]/30"
              >
                <div>
                  <div className="flex items-center justify-between">
                    <span className="grid size-10 place-items-center rounded-xl bg-[#FAF9F6] text-[#183F32] border border-[#E9E5DB]">
                      <Icon className="size-5" />
                    </span>
                    <span className="rounded-full bg-[#FAF9F6] px-2.5 py-0.5 text-[10px] font-semibold text-[#397454] border border-[#E9E5DB]">
                      {p.badge}
                    </span>
                  </div>

                  <h3 className="mt-4 font-display text-base font-semibold text-[#18211D]">
                    {p.title}
                  </h3>
                  <p className="mt-2 text-xs leading-relaxed text-[#6F7770]">
                    {p.description}
                  </p>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </section>
  )
}

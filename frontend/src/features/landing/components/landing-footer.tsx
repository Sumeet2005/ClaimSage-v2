import { Link } from 'react-router-dom'
import { ShieldCheck, ArrowUp } from 'lucide-react'

function GithubIcon({ className = 'size-4' }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="currentColor">
      <path
        fillRule="evenodd"
        clipRule="evenodd"
        d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.53 1.032 1.53 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z"
      />
    </svg>
  )
}

export function LandingFooter() {
  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <footer className="border-t border-[#E9E5DB] bg-[#FAF9F6] text-[#18211D]">
      <div className="mx-auto max-w-[1400px] px-4 py-16 sm:px-6 lg:px-8">
        <div className="grid gap-12 lg:grid-cols-12">
          {/* Brand & Mission Statement */}
          <div className="lg:col-span-4">
            <Link
              to="/"
              className="inline-flex items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
            >
              <span className="grid size-9 place-items-center rounded-xl bg-[#183F32] text-white shadow-xs">
                <ShieldCheck className="size-5" strokeWidth={1.9} />
              </span>
              <span className="font-display text-xl font-bold tracking-tight text-[#18211D]">
                ClaimSage
              </span>
            </Link>

            <p className="mt-4 max-w-sm text-xs leading-relaxed text-[#6F7770]">
              An enterprise AI investigation copilot designed for insurance claims adjusters, policy specialists, and supervisory teams. Powered by LangGraph, pgvector, and Reciprocal Rank Fusion.
            </p>

            <div className="mt-6 flex items-center gap-3">
              <a
                href="https://github.com/Sumeet2005/ClaimSage-v2"
                target="_blank"
                rel="noopener noreferrer"
                className="grid size-9 place-items-center rounded-xl border border-[#E9E5DB] bg-white text-[#18211D] transition-colors hover:bg-[#FAF9F6]"
                aria-label="GitHub Repository"
              >
                <GithubIcon className="size-4" />
              </a>
              <span className="text-xs text-[#6F7770]">
                Repository: <span className="font-mono text-[#183F32]">Sumeet2005/ClaimSage-v2</span>
              </span>
            </div>
          </div>

          {/* Navigation Columns */}
          <div className="lg:col-span-8 grid grid-cols-2 gap-8 sm:grid-cols-4 text-xs">
            {/* Column 1: Product */}
            <div>
              <p className="font-semibold uppercase tracking-wider text-[#18211D]">
                Product
              </p>
              <ul className="mt-4 space-y-2.5 text-[#6F7770]">
                <li>
                  <a href="#product" className="hover:text-[#183F32] transition-colors">
                    Overview
                  </a>
                </li>
                <li>
                  <a href="#product-preview" className="hover:text-[#183F32] transition-colors">
                    Dashboard Interface
                  </a>
                </li>
                <li>
                  <a href="#workflow" className="hover:text-[#183F32] transition-colors">
                    8-Stage Workflow
                  </a>
                </li>
                <li>
                  <a href="#rag" className="hover:text-[#183F32] transition-colors">
                    Contextual Hybrid RAG
                  </a>
                </li>
                <li>
                  <Link to="/login" className="font-medium text-[#183F32] hover:underline">
                    Adjuster Workspace
                  </Link>
                </li>
              </ul>
            </div>

            {/* Column 2: Specialist Agents */}
            <div>
              <p className="font-semibold uppercase tracking-wider text-[#18211D]">
                AI Specialists
              </p>
              <ul className="mt-4 space-y-2.5 text-[#6F7770]">
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Supervisor Agent
                  </a>
                </li>
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Claim Intake Agent
                  </a>
                </li>
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Evidence Analyst
                  </a>
                </li>
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Policy Analyst
                  </a>
                </li>
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Repair Estimate Analyst
                  </a>
                </li>
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Risk & Anomaly Agent
                  </a>
                </li>
                <li>
                  <a href="#agents" className="hover:text-[#183F32] transition-colors">
                    Review & Report Agent
                  </a>
                </li>
              </ul>
            </div>

            {/* Column 3: Architecture & Security */}
            <div>
              <p className="font-semibold uppercase tracking-wider text-[#18211D]">
                Platform
              </p>
              <ul className="mt-4 space-y-2.5 text-[#6F7770]">
                <li>
                  <a href="#architecture" className="hover:text-[#183F32] transition-colors">
                    System Architecture
                  </a>
                </li>
                <li>
                  <a href="#security" className="hover:text-[#183F32] transition-colors">
                    Role-Based Access (RBAC)
                  </a>
                </li>
                <li>
                  <a href="#security" className="hover:text-[#183F32] transition-colors">
                    Immutable Audit Trail
                  </a>
                </li>
                <li>
                  <a href="#docs" className="hover:text-[#183F32] transition-colors">
                    Deterministic Fallback
                  </a>
                </li>
                <li>
                  <a href="#docs" className="hover:text-[#183F32] transition-colors">
                    Docker Compose
                  </a>
                </li>
              </ul>
            </div>

            {/* Column 4: Compliance */}
            <div>
              <p className="font-semibold uppercase tracking-wider text-[#18211D]">
                Governance
              </p>
              <ul className="mt-4 space-y-2.5 text-[#6F7770]">
                <li>
                  <span className="text-[#183F32] font-medium">Assistive Copilot Only</span>
                </li>
                <li>
                  <span>Zero Autonomous Settlement</span>
                </li>
                <li>
                  <span>Verbatim Quote Verification</span>
                </li>
                <li>
                  <span>RFC 6901 Pointer Schema</span>
                </li>
                <li>
                  <button
                    type="button"
                    onClick={scrollToTop}
                    className="inline-flex items-center gap-1 text-[#397454] hover:underline pt-2 font-medium"
                  >
                    <ArrowUp className="size-3" />
                    <span>Back to Top</span>
                  </button>
                </li>
              </ul>
            </div>
          </div>
        </div>

        {/* Bottom Legal Bar */}
        <div className="mt-12 flex flex-col md:flex-row items-center justify-between border-t border-[#E9E5DB] pt-8 text-[11px] text-[#6F7770] gap-4">
          <p>
            © {new Date().getFullYear()} ClaimSage. All rights reserved. Decision-support copilot for licensed claims investigators.
          </p>

          <p className="text-center md:text-right">
            ClaimSage assists human investigators. It does not autonomously approve, reject, settle, or pay insurance claims.
          </p>
        </div>
      </div>
    </footer>
  )
}

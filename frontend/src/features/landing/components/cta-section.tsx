import { Link } from 'react-router-dom'
import { ArrowRight, ShieldCheck, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'

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

export function CtaSection() {
  return (
    <section className="relative overflow-hidden border-b border-[#E9E5DB] bg-[#FAF9F6] py-20 sm:py-28">
      {/* Background radial glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 size-[600px] rounded-full bg-[#EDE7D9]/40 blur-3xl"
      />

      <div className="relative mx-auto max-w-4xl px-4 text-center sm:px-6 lg:px-8">
        <div className="inline-flex items-center gap-2 rounded-full border border-[#DDE9DF] bg-white px-3.5 py-1 text-xs font-semibold text-[#183F32] shadow-2xs">
          <ShieldCheck className="size-4 text-[#397454]" />
          <span>Enterprise Investigation Copilot</span>
        </div>

        <h2 className="mt-6 font-display text-4xl font-semibold tracking-[-0.04em] text-[#18211D] sm:text-5xl lg:text-[52px] leading-tight">
          Bring clarity and intelligence to every investigation.
        </h2>

        <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-[#6F7770] sm:text-lg">
          Equip claims adjusters, forensic analysts, and supervisory teams with an auditable, multi-agent platform that treats claim evidence as strictly verifiable data.
        </p>

        <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
          <Link to="/login">
            <Button
              size="lg"
              className="h-12 gap-2.5 rounded-xl bg-[#183F32] px-7 text-sm font-semibold text-white shadow-md hover:bg-[#245744]"
            >
              <Sparkles className="size-4 text-[#EDE7D9]" />
              <span>Explore ClaimSage</span>
              <ArrowRight className="size-4" />
            </Button>
          </Link>

          <a
            href="https://github.com/Sumeet2005/ClaimSage-v2"
            target="_blank"
            rel="noopener noreferrer"
          >
            <Button
              size="lg"
              variant="outline"
              className="h-12 gap-2.5 border-[#E9E5DB] bg-white px-6 text-sm font-semibold text-[#18211D] hover:bg-[#FAF9F6]"
            >
              <GithubIcon className="size-4" />
              <span>View on GitHub</span>
            </Button>
          </a>
        </div>

        <p className="mt-8 text-xs text-[#6F7770]">
          Zero autonomous claim adjudication · Human oversight strictly required · Defensible audit trail
        </p>
      </div>
    </section>
  )
}

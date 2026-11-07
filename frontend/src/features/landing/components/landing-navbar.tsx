import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  Menu,
  ShieldCheck,
  X,
  Sparkles,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useAuth } from '@/features/auth/auth-context'

export function LandingNavbar() {
  const { status, employee } = useAuth()
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false)
  const isAuthenticated = status === 'authenticated'

  const navLinks = [
    { label: 'Product', href: '#product' },
    { label: 'AI Agents', href: '#agents' },
    { label: 'Workflow', href: '#workflow' },
    { label: 'Evidence RAG', href: '#rag' },
    { label: 'Security', href: '#security' },
    { label: 'Architecture', href: '#architecture' },
    { label: 'Documentation', href: '#docs' },
  ]

  const closeMobile = () => setMobileMenuOpen(false)

  return (
    <header className="sticky top-0 z-50 border-b border-[#E9E5DB] bg-[#FAF9F6]/90 backdrop-blur-md transition-all">
      <div className="mx-auto flex h-16 w-full max-w-[1400px] items-center justify-between px-4 sm:px-6 lg:px-8">
        {/* Brand */}
        <div className="flex items-center gap-6">
          <Link
            aria-label="ClaimSage home"
            className="group flex items-center gap-3 rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
            to="/"
          >
            <span className="grid size-9 place-items-center rounded-xl bg-[#183F32] text-[#FAF9F6] shadow-sm transition-transform duration-200 group-hover:scale-105">
              <ShieldCheck className="size-5 text-[#FAF9F6]" strokeWidth={1.9} />
            </span>
            <div className="flex flex-col">
              <span className="font-display text-[19px] font-bold tracking-tight text-[#18211D]">
                ClaimSage
              </span>
              <span className="text-[10px] font-medium tracking-wider text-[#6F7770] uppercase">
                Investigation AI
              </span>
            </div>
          </Link>

          {/* System status pill */}
          <div className="hidden items-center gap-1.5 rounded-full border border-[#DDE9DF] bg-[#FAF9F6] px-2.5 py-0.5 text-[11px] font-medium text-[#183F32] md:inline-flex">
            <span className="size-1.5 rounded-full bg-[#397454]" />
            <span>Multi-Agent Investigation Platform</span>
          </div>
        </div>

        {/* Desktop Navigation Links */}
        <nav aria-label="Landing page sections" className="hidden lg:flex items-center gap-1">
          {navLinks.map((link) => (
            <a
              key={link.href}
              href={link.href}
              className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-[#6F7770] transition-colors hover:bg-white hover:text-[#18211D]"
            >
              {link.label}
            </a>
          ))}
        </nav>

        {/* CTA Buttons */}
        <div className="hidden sm:flex items-center gap-3">
          {isAuthenticated ? (
            <Link to="/dashboard">
              <Button
                variant="default"
                className="h-9 gap-2 rounded-xl bg-[#183F32] px-4 text-xs font-semibold text-white shadow-sm hover:bg-[#245744]"
              >
                <Sparkles className="size-3.5 text-[#EDE7D9]" />
                <span>Open Workspace</span>
                <ArrowRight className="size-3.5" />
              </Button>
            </Link>
          ) : (
            <>
              <Link to="/login">
                <Button
                  variant="ghost"
                  className="h-9 rounded-xl px-3 text-xs font-medium text-[#18211D] hover:bg-white"
                >
                  Sign in
                </Button>
              </Link>
              <Link to="/login">
                <Button
                  variant="default"
                  className="h-9 gap-2 rounded-xl bg-[#183F32] px-4 text-xs font-semibold text-white shadow-sm hover:bg-[#245744]"
                >
                  <span>Get Started</span>
                  <ArrowRight className="size-3.5" />
                </Button>
              </Link>
            </>
          )}
        </div>

        {/* Mobile menu button */}
        <div className="flex sm:hidden items-center gap-2">
          {isAuthenticated ? (
            <Link to="/dashboard">
              <Button size="sm" className="h-8 bg-[#183F32] text-xs text-white">
                Workspace
              </Button>
            </Link>
          ) : (
            <Link to="/login">
              <Button size="sm" className="h-8 bg-[#183F32] text-xs text-white">
                Sign in
              </Button>
            </Link>
          )}
          <button
            type="button"
            aria-label="Toggle navigation menu"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            className="grid size-9 place-items-center rounded-lg border border-[#E9E5DB] bg-white text-[#18211D] hover:bg-[#FAF9F6]"
          >
            {mobileMenuOpen ? <X className="size-5" /> : <Menu className="size-5" />}
          </button>
        </div>
      </div>

      {/* Mobile Drawer */}
      {mobileMenuOpen && (
        <div className="border-b border-[#E9E5DB] bg-white px-4 py-4 sm:hidden">
          <nav className="flex flex-col gap-1">
            {navLinks.map((link) => (
              <a
                key={link.href}
                href={link.href}
                onClick={closeMobile}
                className="rounded-lg px-3 py-2 text-sm font-medium text-[#18211D] hover:bg-[#FAF9F6]"
              >
                {link.label}
              </a>
            ))}
            <div className="mt-3 flex flex-col gap-2 pt-3 border-t border-[#E9E5DB]">
              {isAuthenticated ? (
                <div className="flex items-center justify-between px-2 py-1 text-xs text-[#6F7770]">
                  <span>Signed in as {employee?.display_name ?? 'User'}</span>
                  <Link
                    to="/dashboard"
                    onClick={closeMobile}
                    className="font-semibold text-[#183F32] hover:underline"
                  >
                    Go to Workspace →
                  </Link>
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <Link to="/login" onClick={closeMobile} className="w-1/2">
                    <Button variant="secondary" className="w-full text-xs">
                      Sign in
                    </Button>
                  </Link>
                  <Link to="/login" onClick={closeMobile} className="w-1/2">
                    <Button className="w-full bg-[#183F32] text-xs text-white">
                      Get Started
                    </Button>
                  </Link>
                </div>
              )}
            </div>
          </nav>
        </div>
      )}
    </header>
  )
}

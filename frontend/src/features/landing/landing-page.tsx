import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { motion, useScroll, useSpring } from 'motion/react'
import { ArrowUp, Sparkles } from 'lucide-react'
import { useAuth } from '@/features/auth/auth-context'
import { LandingNavbar } from './components/landing-navbar'
import { HeroSection } from './components/hero-section'
import { CapabilityStrip } from './components/capability-strip'
import { ProblemSolutionSection } from './components/problem-solution-section'
import { AgentIntelligenceSection } from './components/agent-intelligence-section'
import { WorkflowSection } from './components/workflow-section'
import { ProductShowcaseSection } from './components/product-showcase-section'
import { RagIntelligenceSection } from './components/rag-intelligence-section'
import { SecurityGovernanceSection } from './components/security-governance-section'
import { ArchitectureSection } from './components/architecture-section'
import { DocumentationSection } from './components/documentation-section'
import { CtaSection } from './components/cta-section'
import { LandingFooter } from './components/landing-footer'

export function LandingPage() {
  const { status, employee } = useAuth()
  const [showScrollTop, setShowScrollTop] = useState(false)
  const isAuthenticated = status === 'authenticated'

  const { scrollYProgress } = useScroll()
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 100,
    damping: 30,
    restDelta: 0.001,
  })

  useEffect(() => {
    const handleScroll = () => {
      setShowScrollTop(window.scrollY > 400)
    }
    window.addEventListener('scroll', handleScroll, { passive: true })
    return () => window.removeEventListener('scroll', handleScroll)
  }, [])

  const scrollToTop = () => {
    window.scrollTo({ top: 0, behavior: 'smooth' })
  }

  return (
    <div className="relative min-h-screen bg-[#FAF9F6] text-[#18211D] selection:bg-[#183F32] selection:text-white">
      {/* Top Reading Progress Bar */}
      <motion.div
        className="fixed top-0 left-0 right-0 z-50 h-1 bg-[#183F32] origin-left"
        style={{ scaleX }}
      />

      {/* Floating authenticated indicator banner */}
      {isAuthenticated && (
        <div className="relative z-40 bg-[#183F32] px-4 py-2 text-center text-xs text-white">
          <div className="mx-auto flex max-w-7xl items-center justify-center gap-2">
            <Sparkles className="size-3.5 text-[#EDE7D9]" />
            <span>
              Signed in as <strong>{employee?.display_name ?? 'ClaimSage Adjuster'}</strong> ({employee?.role ?? 'Analyst'})
            </span>
            <span className="text-[#EDE7D9]">·</span>
            <Link
              to="/dashboard"
              className="font-semibold underline underline-offset-2 text-[#EDE7D9] hover:text-white"
            >
              Enter Investigation Workspace →
            </Link>
          </div>
        </div>
      )}

      {/* Navigation Header */}
      <LandingNavbar />

      {/* Main Content Sections */}
      <main>
        {/* Hero Section with Interactive Agent Mesh */}
        <HeroSection />

        {/* Capability Strip */}
        <CapabilityStrip />

        {/* The Problem & Solution */}
        <ProblemSolutionSection />

        {/* Multi-Agent Intelligence (Signature Section) */}
        <AgentIntelligenceSection />

        {/* End-to-End Investigation Workflow */}
        <WorkflowSection />

        {/* Product Showcase (Dashboard, Details, Runner, Reports, Review) */}
        <ProductShowcaseSection />

        {/* Contextual Hybrid RAG Intelligence */}
        <RagIntelligenceSection />

        {/* Security, Governance, and Human Oversight */}
        <SecurityGovernanceSection />

        {/* Architecture & Docker Topology */}
        <ArchitectureSection />

        {/* Documentation & Specifications */}
        <DocumentationSection />

        {/* Final CTA */}
        <CtaSection />
      </main>

      {/* Footer */}
      <LandingFooter />

      {/* Back to top floating button */}
      {showScrollTop && (
        <button
          type="button"
          onClick={scrollToTop}
          aria-label="Scroll back to top"
          className="fixed bottom-6 right-6 z-40 grid size-11 place-items-center rounded-full border border-[#E9E5DB] bg-white text-[#183F32] shadow-lg transition-transform hover:scale-105 active:scale-95"
        >
          <ArrowUp className="size-5" />
        </button>
      )}
    </div>
  )
}

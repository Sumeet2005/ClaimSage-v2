import { useState, useEffect, useRef, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight,
  ShieldCheck,
  Cpu,
  Layers,
  FileSearch,
  Scale,
  Wrench,
  AlertTriangle,
  FileCheck2,
  Activity,
  Play,
  Pause,
  RotateCcw,
  Check,
  Info,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { CLAIM_AGENTS } from '../data/agent-data'

interface ExecutionStep {
  agentId: string
  stageLabel: string
  detail: string
  fromId: string
  toId: string
}

const MOTOR_STEPS: ExecutionStep[] = [
  {
    agentId: 'supervisor',
    stageLabel: 'Supervisor Planning',
    detail: 'Inspecting claim facts & allocating pre-invocation token budgets',
    fromId: 'supervisor',
    toId: 'supervisor',
  },
  {
    agentId: 'intake',
    stageLabel: 'Claim Intake Validation',
    detail: 'Auditing document manifests & extracting mandatory inventory',
    fromId: 'supervisor',
    toId: 'intake',
  },
  {
    agentId: 'evidence',
    stageLabel: 'Evidence & Chronology',
    detail: 'Constructing chronological timeline with verbatim chunk quotes',
    fromId: 'intake',
    toId: 'evidence',
  },
  {
    agentId: 'policy',
    stageLabel: 'Policy Clause Grounding',
    detail: 'Evaluating coverage sub-limits, deductibles & exclusion terms',
    fromId: 'evidence',
    toId: 'policy',
  },
  {
    agentId: 'repair',
    stageLabel: 'Repair Estimate Arithmetic',
    detail: 'Executing repair rules & statutory parts depreciation schedules',
    fromId: 'policy',
    toId: 'repair',
  },
  {
    agentId: 'risk',
    stageLabel: 'Risk & Anomaly Surfacing',
    detail: 'Flagging billing discrepancies while isolating facts from hypotheses',
    fromId: 'repair',
    toId: 'risk',
  },
  {
    agentId: 'review_report',
    stageLabel: 'Executive Report Synthesis',
    detail: 'Validating RFC 6901 deep-link pointers & compiling final dossier',
    fromId: 'risk',
    toId: 'review_report',
  },
]

const HEALTH_STEPS: ExecutionStep[] = [
  {
    agentId: 'supervisor',
    stageLabel: 'Supervisor Planning',
    detail: 'Claim type health: Repair Estimate automatically bypassed',
    fromId: 'supervisor',
    toId: 'supervisor',
  },
  {
    agentId: 'intake',
    stageLabel: 'Claim Intake Validation',
    detail: 'Auditing hospital discharge summary & itemized room bills',
    fromId: 'supervisor',
    toId: 'intake',
  },
  {
    agentId: 'evidence',
    stageLabel: 'Evidence & Chronology',
    detail: 'Constructing chronological clinical timeline across hospital stay',
    fromId: 'intake',
    toId: 'evidence',
  },
  {
    agentId: 'policy',
    stageLabel: 'Policy Clause Grounding',
    detail: 'Applying 1% SI room rent capping & PED waiting period validation',
    fromId: 'evidence',
    toId: 'policy',
  },
  {
    agentId: 'risk',
    stageLabel: 'Risk & Anomaly Surfacing',
    detail: 'Detecting unbundled medical codes & duplicate diagnostic fees',
    fromId: 'policy',
    toId: 'risk',
  },
  {
    agentId: 'review_report',
    stageLabel: 'Executive Report Synthesis',
    detail: 'Synthesizing executive report with 100% evidence provenance',
    fromId: 'risk',
    toId: 'review_report',
  },
]

type PlaybackState = 'idle' | 'running' | 'paused' | 'completed'

export function HeroSection() {
  const [claimMode, setClaimMode] = useState<'motor' | 'health'>('motor')
  const [selectedAgentId, setSelectedAgentId] = useState<string>('supervisor')
  const [playbackState, setPlaybackState] = useState<PlaybackState>('idle')
  const [currentStepIndex, setCurrentStepIndex] = useState<number>(-1)
  const [completedAgentIds, setCompletedAgentIds] = useState<string[]>([])
  const [hoveredAgentId, setHoveredAgentId] = useState<string | null>(null)

  const timerRef = useRef<number | null>(null)
  const advanceStepRef = useRef<(idx: number) => void>(() => {})

  const steps = claimMode === 'motor' ? MOTOR_STEPS : HEALTH_STEPS
  const currentStep = currentStepIndex >= 0 ? steps[currentStepIndex] : null

  const fallbackAgent = CLAIM_AGENTS[0]!
  const inspectedAgentId = hoveredAgentId ?? selectedAgentId
  const inspectedAgent =
    CLAIM_AGENTS.find((a) => a.id === inspectedAgentId) ?? fallbackAgent

  // Node spatial coordinates within 600x480 coordinate space
  const nodePositions: Record<
    string,
    { x: number; y: number; label: string; icon: typeof ShieldCheck }
  > = {
    supervisor: { x: 300, y: 235, label: 'Supervisor', icon: Cpu },
    intake: { x: 135, y: 110, label: 'Intake Agent', icon: FileSearch },
    evidence: { x: 465, y: 100, label: 'Evidence Analyst', icon: Layers },
    policy: { x: 505, y: 260, label: 'Policy Analyst', icon: Scale },
    repair: { x: 445, y: 395, label: 'Repair Estimate', icon: Wrench },
    risk: { x: 155, y: 390, label: 'Risk & Anomaly', icon: AlertTriangle },
    review_report: { x: 95, y: 250, label: 'Review & Report', icon: FileCheck2 },
  }

  const supPos = nodePositions['supervisor'] ?? { x: 300, y: 235 }
  const intakePos = nodePositions['intake'] ?? { x: 135, y: 110 }
  const evidencePos = nodePositions['evidence'] ?? { x: 465, y: 100 }
  const policyPos = nodePositions['policy'] ?? { x: 505, y: 260 }
  const repairPos = nodePositions['repair'] ?? { x: 445, y: 395 }
  const riskPos = nodePositions['risk'] ?? { x: 155, y: 390 }
  const reviewPos = nodePositions['review_report'] ?? { x: 95, y: 250 }

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  // Advance step logic
  const advanceStep = useCallback(
    (nextIdx: number) => {
      if (nextIdx >= steps.length) {
        // Complete the sequence
        clearTimer()
        setPlaybackState('completed')
        setSelectedAgentId('supervisor')
        // Mark all active steps as completed
        const allIds = steps.map((s) => s.agentId)
        setCompletedAgentIds(Array.from(new Set([...allIds, 'supervisor'])))
        return
      }

      setCurrentStepIndex(nextIdx)
      const step = steps[nextIdx]
      if (step) {
        setSelectedAgentId(step.agentId)
        // Mark previous agent as completed
        if (nextIdx > 0) {
          const prev = steps[nextIdx - 1]
          if (prev) {
            setCompletedAgentIds((prevList) =>
              prevList.includes(prev.agentId) ? prevList : [...prevList, prev.agentId],
            )
          }
        }
      }

      // Schedule next step transition (1800ms per stage)
      timerRef.current = window.setTimeout(() => {
        advanceStepRef.current(nextIdx + 1)
      }, 1800)
    },
    [steps, clearTimer],
  )

  useEffect(() => {
    advanceStepRef.current = advanceStep
  }, [advanceStep])

  const handleStart = () => {
    clearTimer()
    setPlaybackState('running')
    setCompletedAgentIds([])
    advanceStep(0)
  }

  const handlePause = () => {
    clearTimer()
    setPlaybackState('paused')
  }

  const handleResume = () => {
    setPlaybackState('running')
    const resumeIndex = currentStepIndex >= 0 ? currentStepIndex : 0
    advanceStep(resumeIndex)
  }

  const handleReset = () => {
    clearTimer()
    setPlaybackState('idle')
    setCurrentStepIndex(-1)
    setCompletedAgentIds([])
    setSelectedAgentId('supervisor')
  }

  const handleClaimModeChange = (mode: 'motor' | 'health') => {
    if (mode === claimMode) return
    clearTimer()
    setClaimMode(mode)
    setPlaybackState('idle')
    setCurrentStepIndex(-1)
    setCompletedAgentIds([])
    setSelectedAgentId('supervisor')
  }

  useEffect(() => {
    return () => {
      clearTimer()
    }
  }, [clearTimer])

  // Active step coordinates for dynamic pulse
  const activeFromPos: { x: number; y: number } =
    (currentStep?.fromId && nodePositions[currentStep.fromId]) ? nodePositions[currentStep.fromId]! : supPos
  const activeToPos: { x: number; y: number } =
    (currentStep?.toId && nodePositions[currentStep.toId]) ? nodePositions[currentStep.toId]! : supPos

  const activeAgentId = currentStep?.agentId ?? null

  return (
    <section className="relative overflow-hidden border-b border-[#E9E5DB] bg-[#FAF9F6] py-14 sm:py-20 lg:py-24">
      {/* Refinement 5: Subtle Restrained Ambient Background */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -left-20 top-10 size-[500px] rounded-full bg-gradient-to-tr from-[#DDE9DF]/20 via-[#FAF9F6]/10 to-transparent blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute -right-20 top-20 size-[560px] rounded-full bg-gradient-to-bl from-[#EDE7D9]/25 via-[#DDE9DF]/10 to-transparent blur-3xl"
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 size-[800px] rounded-full bg-gradient-to-b from-[#FAF9F6] via-[#EDE7D9]/15 to-transparent blur-3xl"
      />

      <div className="relative mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        <div className="grid gap-10 lg:grid-cols-12 lg:items-center">
          {/* Refinement 6: Editorial Headline & Messaging */}
          <div className="lg:col-span-5 xl:col-span-5">
            {/* Reassurance pill */}
            <div className="inline-flex items-center gap-2 rounded-full border border-[#DDE9DF] bg-white px-3.5 py-1.5 text-xs font-semibold text-[#183F32] shadow-xs">
              <ShieldCheck className="size-4 text-[#397454]" />
              <span>Multi-Agent Insurance Copilot</span>
            </div>

            {/* Headline with balanced line lengths */}
            <h1 className="mt-6 max-w-[560px] font-display text-4xl font-semibold leading-[1.12] tracking-[-0.04em] text-[#18211D] sm:text-5xl lg:text-[52px] xl:text-[56px]">
              Insurance investigations,
              <br className="hidden sm:inline" /> thoughtfully reimagined.
            </h1>

            {/* Supporting copy */}
            <p className="mt-6 max-w-xl text-base leading-relaxed text-[#6F7770] sm:text-lg">
              An intelligent multi-agent platform that connects claim evidence, policy intelligence and risk analysis into one transparent investigation workflow.
            </p>

            {/* CTAs */}
            <div className="mt-8 flex flex-wrap items-center gap-3.5">
              <Link to="/login">
                <Button
                  size="lg"
                  className="h-12 gap-2.5 rounded-xl bg-[#183F32] px-6 text-sm font-semibold text-white shadow-md transition-all hover:bg-[#245744] hover:shadow-lg"
                >
                  <span>Explore the Platform</span>
                  <ArrowRight className="size-4" />
                </Button>
              </Link>

              <a href="#architecture">
                <Button
                  size="lg"
                  variant="outline"
                  className="h-12 border-[#E9E5DB] bg-white px-5 text-sm font-medium text-[#18211D] hover:bg-[#FAF9F6]"
                >
                  View Architecture
                </Button>
              </a>
            </div>

            {/* Trust Highlights */}
            <div className="mt-10 grid grid-cols-3 gap-3 border-t border-[#E9E5DB] pt-6 text-xs">
              <div>
                <p className="font-semibold text-[#18211D]">Deterministic</p>
                <p className="mt-0.5 text-[#6F7770]">100% Verbatim Quote Grounding</p>
              </div>
              <div>
                <p className="font-semibold text-[#18211D]">Auditable</p>
                <p className="mt-0.5 text-[#6F7770]">RFC 6901 JSON Pointers</p>
              </div>
              <div>
                <p className="font-semibold text-[#18211D]">Strict Guardrails</p>
                <p className="mt-0.5 text-[#6F7770]">Mandatory Human Oversight</p>
              </div>
            </div>
          </div>

          {/* Right Column: Animated Multi-Agent Network Visual */}
          <div className="lg:col-span-7 xl:col-span-7">
            <div className="rounded-3xl border border-[#E9E5DB] bg-white p-5 shadow-[0_16px_40px_-24px_rgba(24,63,50,0.15)] sm:p-7">
              {/* Header bar with Mode switcher & Pulse Controls */}
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[#E9E5DB] pb-4">
                <div className="flex items-center gap-2.5">
                  <span className="grid size-7 place-items-center rounded-lg bg-[#DDE9DF] text-[#183F32]">
                    <Activity className="size-4" />
                  </span>
                  <div>
                    <div className="flex items-center gap-2">
                      <h2 className="text-sm font-semibold text-[#18211D]">
                        LangGraph Specialist Mesh
                      </h2>
                      <span className="rounded bg-[#EDE7D9] px-2 py-0.5 text-[9px] font-bold text-[#183F32] uppercase tracking-wider">
                        Illustrative workflow demo
                      </span>
                    </div>
                    <p className="text-[11px] text-[#6F7770]">
                      Supervisor coordinates specialist agents with verifiable state contracts
                    </p>
                  </div>
                </div>

                {/* Scenario & Playback Controls */}
                <div className="flex items-center gap-2">
                  {/* Claim Type Switcher */}
                  <div className="flex rounded-lg border border-[#E9E5DB] bg-[#FAF9F6] p-0.5 text-xs">
                    <button
                      type="button"
                      onClick={() => handleClaimModeChange('motor')}
                      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                        claimMode === 'motor'
                          ? 'bg-white font-semibold text-[#183F32] shadow-xs'
                          : 'text-[#6F7770] hover:text-[#18211D]'
                      }`}
                    >
                      Motor Claim
                    </button>
                    <button
                      type="button"
                      onClick={() => handleClaimModeChange('health')}
                      className={`rounded-md px-2.5 py-1 text-xs font-medium transition-colors ${
                        claimMode === 'health'
                          ? 'bg-white font-semibold text-[#183F32] shadow-xs'
                          : 'text-[#6F7770] hover:text-[#18211D]'
                      }`}
                    >
                      Health Claim
                    </button>
                  </div>

                  {/* Refinement 4: Interactive Run Pulse Button */}
                  {playbackState === 'idle' && (
                    <button
                      type="button"
                      onClick={handleStart}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[#397454] bg-[#183F32] px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-[#245744]"
                      aria-label="Start illustrative investigation pulse"
                    >
                      <Play className="size-3 fill-current" />
                      <span>Run Pulse</span>
                    </button>
                  )}

                  {playbackState === 'running' && (
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={handlePause}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-[#397454] bg-[#183F32] px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-[#245744]"
                        aria-label="Pause pulse animation"
                      >
                        <Pause className="size-3 fill-current" />
                        <span>Pause</span>
                      </button>
                      <button
                        type="button"
                        onClick={handleReset}
                        className="grid size-8 place-items-center rounded-lg border border-[#E9E5DB] bg-white text-[#6F7770] hover:bg-[#FAF9F6] hover:text-[#18211D]"
                        title="Reset simulation"
                        aria-label="Reset simulation"
                      >
                        <RotateCcw className="size-3.5" />
                      </button>
                    </div>
                  )}

                  {playbackState === 'paused' && (
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        onClick={handleResume}
                        className="inline-flex items-center gap-1.5 rounded-lg border border-[#397454] bg-[#183F32] px-3 py-1.5 text-xs font-semibold text-white shadow-xs transition-colors hover:bg-[#245744]"
                        aria-label="Resume pulse animation"
                      >
                        <Play className="size-3 fill-current" />
                        <span>Resume</span>
                      </button>
                      <button
                        type="button"
                        onClick={handleReset}
                        className="grid size-8 place-items-center rounded-lg border border-[#E9E5DB] bg-white text-[#6F7770] hover:bg-[#FAF9F6] hover:text-[#18211D]"
                        title="Reset simulation"
                        aria-label="Reset simulation"
                      >
                        <RotateCcw className="size-3.5" />
                      </button>
                    </div>
                  )}

                  {playbackState === 'completed' && (
                    <button
                      type="button"
                      onClick={handleStart}
                      className="inline-flex items-center gap-1.5 rounded-lg border border-[#DDE9DF] bg-[#DDE9DF] px-3 py-1.5 text-xs font-semibold text-[#183F32] shadow-xs transition-colors hover:bg-[#DDE9DF]/80"
                      aria-label="Restart illustrative investigation pulse"
                    >
                      <RotateCcw className="size-3" />
                      <span>Restart Pulse</span>
                    </button>
                  )}
                </div>
              </div>

              {/* Stage Progress Bar & Status Pill */}
              <div className="mt-3 flex items-center justify-between text-xs">
                <div className="flex items-center gap-2">
                  {playbackState === 'idle' && (
                    <span className="flex items-center gap-1.5 text-[11px] text-[#6F7770]">
                      <Info className="size-3 text-[#397454]" />
                      <span>Click any agent node or press Run Pulse to inspect execution sequence</span>
                    </span>
                  )}
                  {playbackState === 'running' && (
                    <span className="flex items-center gap-1.5 text-[11px] font-semibold text-[#183F32]">
                      <span className="size-2 animate-ping rounded-full bg-[#397454]" />
                      <span>
                        Stage {currentStepIndex + 1} of {steps.length}: {currentStep?.stageLabel}
                      </span>
                    </span>
                  )}
                  {playbackState === 'paused' && (
                    <span className="text-[11px] font-semibold text-[#B79B6A]">
                      Simulation Paused at Stage {currentStepIndex + 1} of {steps.length}
                    </span>
                  )}
                  {playbackState === 'completed' && (
                    <span className="flex items-center gap-1.5 text-[11px] font-semibold text-[#183F32]">
                      <Check className="size-3 text-[#397454]" />
                      <span>Investigation Sequence Completed · Final Executive Report Ready</span>
                    </span>
                  )}
                </div>

                {claimMode === 'health' && (
                  <span className="rounded bg-[#EDE7D9]/60 px-2 py-0.5 text-[10px] font-medium text-[#183F32]">
                    Repair Analyst Bypassed
                  </span>
                )}
              </div>

              {/* Progress Indicator track */}
              {playbackState !== 'idle' && (
                <div className="mt-2 h-1 w-full overflow-hidden rounded-full bg-[#E9E5DB]">
                  <div
                    className="h-full bg-[#183F32] transition-all duration-300"
                    style={{
                      width: `${
                        playbackState === 'completed'
                          ? 100
                          : ((currentStepIndex + 1) / steps.length) * 100
                      }%`,
                    }}
                  />
                </div>
              )}

              {/* Refinement 2: Interactive SVG Multi-Agent Network Stage */}
              <div
                className="relative mt-3 h-[350px] w-full overflow-hidden rounded-2xl border border-[#E9E5DB]/70 bg-[#FAF9F6] sm:h-[390px]"
                role="region"
                aria-label="Multi-Agent Network Interactive Visualization"
              >
                {/* SVG Connectors & Data Pulses */}
                <svg className="absolute inset-0 size-full" viewBox="0 0 600 480">
                  <defs>
                    <linearGradient id="supervisorRay" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#183F32" stopOpacity="0.8" />
                      <stop offset="100%" stopColor="#397454" stopOpacity="0.4" />
                    </linearGradient>
                    <filter id="pulseGlow" x="-30%" y="-30%" width="160%" height="160%">
                      <feGaussianBlur stdDeviation="3" result="blur" />
                      <feComposite in="SourceGraphic" in2="blur" operator="over" />
                    </filter>
                  </defs>

                  {/* Connectors from Supervisor to each satellite agent */}
                  {Object.entries(nodePositions).map(([id, pos]) => {
                    if (id === 'supervisor') return null
                    const isBypassed = claimMode === 'health' && id === 'repair'
                    const isSelected = inspectedAgentId === id
                    const isActive = activeAgentId === id
                    const isCompleted = completedAgentIds.includes(id)

                    return (
                      <g key={id}>
                        {/* Static / active connector line */}
                        <line
                          x1={supPos.x}
                          y1={supPos.y}
                          x2={pos.x}
                          y2={pos.y}
                          stroke={
                            isBypassed
                              ? '#D8D1C2'
                              : isActive
                                ? '#183F32'
                                : isSelected
                                  ? '#397454'
                                  : isCompleted
                                    ? '#A0A79D'
                                    : '#E9E5DB'
                          }
                          strokeWidth={isActive ? 3 : isSelected ? 2.5 : 1.5}
                          strokeDasharray={isBypassed ? '4,4' : undefined}
                          className="transition-all duration-300"
                        />
                      </g>
                    )
                  })}

                  {/* Sequential Workflow Perimeter Paths */}
                  {/* Intake -> Evidence */}
                  <line
                    x1={intakePos.x}
                    y1={intakePos.y}
                    x2={evidencePos.x}
                    y2={evidencePos.y}
                    stroke="#DDE9DF"
                    strokeWidth="1.5"
                    strokeDasharray="3,3"
                  />
                  {/* Evidence -> Policy */}
                  <line
                    x1={evidencePos.x}
                    y1={evidencePos.y}
                    x2={policyPos.x}
                    y2={policyPos.y}
                    stroke="#DDE9DF"
                    strokeWidth="1.5"
                    strokeDasharray="3,3"
                  />
                  {/* Policy -> Repair (Motor) or Policy -> Risk (Health Bypass) */}
                  {claimMode === 'motor' ? (
                    <>
                      <line
                        x1={policyPos.x}
                        y1={policyPos.y}
                        x2={repairPos.x}
                        y2={repairPos.y}
                        stroke="#DDE9DF"
                        strokeWidth="1.5"
                        strokeDasharray="3,3"
                      />
                      <line
                        x1={repairPos.x}
                        y1={repairPos.y}
                        x2={riskPos.x}
                        y2={riskPos.y}
                        stroke="#DDE9DF"
                        strokeWidth="1.5"
                        strokeDasharray="3,3"
                      />
                    </>
                  ) : (
                    /* Health Mode direct bypass path */
                    <path
                      d={`M${policyPos.x},${policyPos.y} Q 300 440 ${riskPos.x},${riskPos.y}`}
                      fill="none"
                      stroke="#397454"
                      strokeWidth="1.5"
                      strokeDasharray="4,4"
                      className="opacity-70"
                    />
                  )}
                  {/* Risk -> Review & Report */}
                  <line
                    x1={riskPos.x}
                    y1={riskPos.y}
                    x2={reviewPos.x}
                    y2={reviewPos.y}
                    stroke="#DDE9DF"
                    strokeWidth="1.5"
                    strokeDasharray="3,3"
                  />
                  {/* Review & Report -> Supervisor */}
                  <line
                    x1={reviewPos.x}
                    y1={reviewPos.y}
                    x2={supPos.x}
                    y2={supPos.y}
                    stroke="#DDE9DF"
                    strokeWidth="1.5"
                    strokeDasharray="3,3"
                  />

                  {/* Dynamic Sage-Green Data Pulse traveling along active step */}
                  {playbackState === 'running' && currentStep && (
                    <g filter="url(#pulseGlow)">
                      {/* Pulse beacon */}
                      <circle r="5" fill="#397454">
                        <animateMotion
                          path={`M${activeFromPos.x},${activeFromPos.y} L${activeToPos.x},${activeToPos.y}`}
                          dur="1.2s"
                          repeatCount="indefinite"
                        />
                      </circle>
                      {/* Trailing particle */}
                      <circle r="3" fill="#183F32" opacity="0.6">
                        <animateMotion
                          path={`M${activeFromPos.x},${activeFromPos.y} L${activeToPos.x},${activeToPos.y}`}
                          dur="1.2s"
                          begin="0.15s"
                          repeatCount="indefinite"
                        />
                      </circle>
                    </g>
                  )}

                  {/* Ambient idle pulses from supervisor when idle */}
                  {playbackState === 'idle' && (
                    <circle r="3" fill="#397454" opacity="0.6">
                      <animateMotion
                        path={`M${supPos.x},${supPos.y} L${intakePos.x},${intakePos.y}`}
                        dur="3s"
                        repeatCount="indefinite"
                      />
                    </circle>
                  )}
                </svg>

                {/* Refinement 3: Accessible Interactive HTML Agent Nodes */}
                <div className="absolute inset-0">
                  {Object.entries(nodePositions).map(([id, pos]) => {
                    const Icon = pos.icon
                    const isSupervisor = id === 'supervisor'
                    const isBypassed = claimMode === 'health' && id === 'repair'
                    const isSelected = inspectedAgentId === id
                    const isActive = activeAgentId === id
                    const isCompleted = completedAgentIds.includes(id)

                    const leftPct = (pos.x / 600) * 100
                    const topPct = (pos.y / 480) * 100

                    return (
                      <button
                        key={id}
                        type="button"
                        disabled={isBypassed}
                        onClick={() => setSelectedAgentId(id)}
                        onMouseEnter={() => setHoveredAgentId(id)}
                        onMouseLeave={() => setHoveredAgentId(null)}
                        onFocus={() => setSelectedAgentId(id)}
                        style={{
                          left: `${leftPct}%`,
                          top: `${topPct}%`,
                          transform: 'translate(-50%, -50%)',
                        }}
                        aria-label={`Agent node: ${pos.label}${
                          isBypassed ? ' (Bypassed for health claims)' : ''
                        }`}
                        aria-pressed={isSelected}
                        className={`group absolute cursor-pointer select-none transition-all duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#183F32] focus-visible:ring-offset-2 rounded-2xl ${
                          isBypassed
                            ? 'opacity-40 cursor-not-allowed'
                            : 'opacity-100 hover:scale-105'
                        }`}
                      >
                        <div
                          className={`flex flex-col items-center gap-1.5 ${
                            isActive ? 'scale-110' : isSelected ? 'scale-105' : ''
                          }`}
                        >
                          <div
                            className={`relative grid place-items-center rounded-2xl shadow-md transition-all ${
                              isSupervisor
                                ? isActive || (playbackState === 'completed' && isCompleted)
                                  ? 'size-14 bg-[#183F32] text-white ring-4 ring-[#397454]/40 ring-offset-2 ring-offset-[#FAF9F6]'
                                  : 'size-14 bg-[#183F32] text-white ring-3 ring-[#DDE9DF]'
                                : isActive
                                  ? 'size-12 bg-[#245744] text-white ring-4 ring-[#397454]/40 ring-offset-2 ring-offset-[#FAF9F6]'
                                  : isSelected
                                    ? 'size-12 bg-[#183F32] text-white ring-3 ring-[#EDE7D9]'
                                    : isCompleted
                                      ? 'size-11 border-2 border-[#397454] bg-[#DDE9DF]/40 text-[#183F32]'
                                      : isBypassed
                                        ? 'size-11 border border-dashed border-[#D8D1C2] bg-white text-[#6F7770]'
                                        : 'size-11 border border-[#E9E5DB] bg-white text-[#183F32]'
                            }`}
                          >
                            <Icon className={isSupervisor ? 'size-6' : 'size-5'} />

                            {/* Completed Checkmark Badge */}
                            {isCompleted && !isActive && !isBypassed && (
                              <span
                                className="absolute -top-1.5 -right-1.5 grid size-5 place-items-center rounded-full bg-[#183F32] text-white shadow-xs border-2 border-white"
                                title="Stage Completed"
                              >
                                <Check className="size-2.5" strokeWidth={3} />
                              </span>
                            )}

                            {/* Active Pulse beacon badge */}
                            {isActive && (
                              <span className="absolute -top-1.5 -right-1.5 size-3.5 rounded-full bg-[#397454] ring-2 ring-white animate-pulse" />
                            )}
                          </div>

                          <div className="flex flex-col items-center">
                            <span
                              className={`rounded-md px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap transition-colors ${
                                isActive
                                  ? 'bg-[#183F32] text-white shadow-xs'
                                  : isSelected
                                    ? 'bg-[#245744] text-white shadow-xs'
                                    : 'bg-white/95 text-[#18211D] shadow-2xs border border-[#E9E5DB]'
                              }`}
                            >
                              {pos.label}
                            </span>
                            {isBypassed && (
                              <span className="text-[9px] font-medium text-[#6F7770]">
                                (Health Bypassed)
                              </span>
                            )}
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* Bottom Inspector Drawer: Real Agent Details & Output Contract */}
              <div className="mt-4 rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-4 transition-all">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="font-display text-sm font-semibold text-[#18211D]">
                      {inspectedAgent.name}
                    </span>
                    <code className="rounded bg-white px-1.5 py-0.5 font-mono text-[11px] text-[#397454] border border-[#E9E5DB]">
                      {inspectedAgent.sourceFile}
                    </code>
                    {activeAgentId === inspectedAgent.id && (
                      <span className="rounded-full bg-[#DDE9DF] px-2 py-0.5 text-[10px] font-bold text-[#183F32] animate-pulse">
                        Currently Active Stage
                      </span>
                    )}
                  </div>
                  <span className="rounded-full bg-[#DDE9DF] px-2.5 py-0.5 text-[10px] font-semibold text-[#183F32]">
                    Contract: {inspectedAgent.contract.split('(')[0]}
                  </span>
                </div>

                <p className="mt-1.5 text-xs text-[#6F7770]">
                  {inspectedAgent.role}
                </p>

                {/* Real input stream and verified output artifact */}
                <div className="mt-3 grid gap-2 sm:grid-cols-2 text-xs">
                  <div className="rounded-xl border border-[#E9E5DB] bg-white p-2.5">
                    <p className="text-[10px] font-semibold text-[#6F7770] uppercase tracking-wider">
                      Input Dependency
                    </p>
                    <p className="mt-1 text-[11px] font-medium text-[#18211D] truncate">
                      {inspectedAgent.inputDependencies[0]}
                    </p>
                  </div>
                  <div className="rounded-xl border border-[#E9E5DB] bg-white p-2.5">
                    <p className="text-[10px] font-semibold text-[#6F7770] uppercase tracking-wider">
                      Verified Output Artifact
                    </p>
                    <p className="mt-1 text-[11px] font-medium text-[#18211D] truncate">
                      {inspectedAgent.samplePayload.findingsSummary}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

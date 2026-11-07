import { useState } from 'react'
import {
  FileText,
  Search,
  Layers,
  Scale,
  Wrench,
  AlertTriangle,
  FileCheck2,
  UserCheck,
  ArrowRight,
  ArrowLeft,
  GitBranch,
  ShieldAlert,
  CheckCircle,
} from 'lucide-react'
import { WORKFLOW_STEPS } from '../data/workflow-data'

export function WorkflowSection() {
  const [activeStepIndex, setActiveStepIndex] = useState(0)
  const [claimType, setClaimType] = useState<'motor' | 'health'>('motor')

  const fallbackStep = WORKFLOW_STEPS[0]!
  const currentStep = WORKFLOW_STEPS[activeStepIndex] ?? fallbackStep

  const stepIcons = [
    FileText,
    Search,
    Layers,
    Scale,
    Wrench,
    AlertTriangle,
    FileCheck2,
    UserCheck,
  ]

  const handleNext = () => {
    if (activeStepIndex < WORKFLOW_STEPS.length - 1) {
      if (claimType === 'health' && activeStepIndex === 3) {
        // Skip step 5 (index 4) for health claims
        setActiveStepIndex(5)
      } else {
        setActiveStepIndex(activeStepIndex + 1)
      }
    }
  }

  const handlePrev = () => {
    if (activeStepIndex > 0) {
      if (claimType === 'health' && activeStepIndex === 5) {
        // Step back to step 4 (index 3)
        setActiveStepIndex(3)
      } else {
        setActiveStepIndex(activeStepIndex - 1)
      }
    }
  }

  return (
    <section id="workflow" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
              Autonomous & Transparent
            </p>
            <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
              End-to-end investigation lifecycle.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
              From unstructured PDF ingestion to final human adjuster determination, every stage is deterministic, observable, and strictly guarded against hallucinations.
            </p>
          </div>

          {/* Claim Branch Selector */}
          <div className="flex items-center gap-3 rounded-2xl border border-[#E9E5DB] bg-white p-2">
            <span className="flex items-center gap-1.5 px-2 text-xs font-semibold text-[#18211D]">
              <GitBranch className="size-3.5 text-[#397454]" />
              <span>Routing Mode:</span>
            </span>
            <button
              type="button"
              onClick={() => {
                setClaimType('motor')
              }}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors ${
                claimType === 'motor'
                  ? 'bg-[#183F32] text-white'
                  : 'text-[#6F7770] hover:text-[#18211D]'
              }`}
            >
              Motor (With Repair)
            </button>
            <button
              type="button"
              onClick={() => {
                setClaimType('health')
                if (activeStepIndex === 4) setActiveStepIndex(5)
              }}
              className={`rounded-xl px-3 py-1.5 text-xs font-semibold transition-colors ${
                claimType === 'health'
                  ? 'bg-[#183F32] text-white'
                  : 'text-[#6F7770] hover:text-[#18211D]'
              }`}
            >
              Health (Bypass Repair)
            </button>
          </div>
        </div>

        {/* Horizontal Timeline Scrubber */}
        <div className="mt-12 overflow-x-auto pb-4">
          <div className="flex items-center gap-2 min-w-[900px]">
            {WORKFLOW_STEPS.map((step, idx) => {
              const Icon = stepIcons[idx] ?? FileText
              const isActive = activeStepIndex === idx
              const isPassed = activeStepIndex > idx
              const isBypassed = claimType === 'health' && idx === 4

              return (
                <div key={step.stepNumber} className="flex-1 flex items-center">
                  <button
                    type="button"
                    disabled={isBypassed}
                    onClick={() => setActiveStepIndex(idx)}
                    className={`flex flex-col items-center gap-2 rounded-2xl p-3 text-center transition-all w-full border ${
                      isBypassed
                        ? 'border-dashed border-[#E9E5DB] bg-[#FAF9F6] opacity-40 cursor-not-allowed'
                        : isActive
                          ? 'border-[#183F32] bg-[#183F32] text-white shadow-sm'
                          : isPassed
                            ? 'border-[#DDE9DF] bg-[#DDE9DF]/30 text-[#183F32]'
                            : 'border-[#E9E5DB] bg-white text-[#6F7770] hover:border-[#DDE9DF]'
                    }`}
                  >
                    <span
                      className={`grid size-9 place-items-center rounded-xl text-xs font-bold ${
                        isActive
                          ? 'bg-[#245744] text-white'
                          : isPassed
                            ? 'bg-[#DDE9DF] text-[#183F32]'
                            : 'bg-[#FAF9F6] text-[#6F7770]'
                      }`}
                    >
                      <Icon className="size-4" />
                    </span>
                    <span className="font-display text-xs font-semibold truncate max-w-[100px]">
                      {step.shortLabel}
                    </span>
                    {isBypassed && (
                      <span className="text-[9px] text-[#6F7770] font-medium">Bypassed</span>
                    )}
                  </button>

                  {idx < WORKFLOW_STEPS.length - 1 && (
                    <div className="mx-1 h-[2px] w-4 bg-[#E9E5DB]" />
                  )}
                </div>
              )
            })}
          </div>
        </div>

        {/* Active Stage Detail Card */}
        <div className="mt-8 rounded-3xl border border-[#E9E5DB] bg-white p-6 sm:p-10 shadow-sm">
          <div className="flex flex-wrap items-center justify-between gap-4 border-b border-[#E9E5DB] pb-6">
            <div className="flex items-center gap-4">
              <span className="grid size-12 place-items-center rounded-2xl bg-[#DDE9DF] font-display text-lg font-bold text-[#183F32]">
                0{currentStep.stepNumber}
              </span>
              <div>
                <div className="flex items-center gap-3">
                  <h3 className="font-display text-2xl font-semibold text-[#18211D]">
                    {currentStep.title}
                  </h3>
                  {currentStep.condition && (
                    <span className="rounded-full border border-[#EDE7D9] bg-[#EDE7D9]/60 px-2.5 py-0.5 text-xs font-medium text-[#183F32]">
                      {currentStep.condition}
                    </span>
                  )}
                </div>
                <code className="mt-1 inline-block font-mono text-xs text-[#397454]">
                  {currentStep.processingPill}
                </code>
              </div>
            </div>

            {/* Step Controls */}
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handlePrev}
                disabled={activeStepIndex === 0}
                className="grid size-9 place-items-center rounded-xl border border-[#E9E5DB] bg-white text-[#18211D] hover:bg-[#FAF9F6] disabled:opacity-40"
              >
                <ArrowLeft className="size-4" />
              </button>
              <button
                type="button"
                onClick={handleNext}
                disabled={activeStepIndex === WORKFLOW_STEPS.length - 1}
                className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-[#183F32] px-4 text-xs font-semibold text-white hover:bg-[#245744] disabled:opacity-40"
              >
                <span>Next Stage</span>
                <ArrowRight className="size-4" />
              </button>
            </div>
          </div>

          <p className="mt-6 text-base leading-relaxed text-[#6F7770]">
            {currentStep.description}
          </p>

          {/* Stage Inputs & Outputs */}
          <div className="mt-8 grid gap-6 md:grid-cols-2">
            <div className="rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-[#6F7770]">
                Stage Ingestion Inputs
              </p>
              <ul className="mt-3 space-y-2">
                {currentStep.inputs.map((inp, idx) => (
                  <li key={idx} className="flex items-center gap-2 text-xs text-[#18211D]">
                    <span className="size-1.5 rounded-full bg-[#183F32]" />
                    <span>{inp}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-5">
              <p className="text-xs font-semibold uppercase tracking-wider text-[#6F7770]">
                Stage Output Artifacts
              </p>
              <ul className="mt-3 space-y-2">
                {currentStep.outputs.map((out, idx) => (
                  <li key={idx} className="flex items-center gap-2 text-xs text-[#18211D]">
                    <CheckCircle className="size-3.5 text-[#397454]" />
                    <span>{out}</span>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Safety & Compliance Guarantee */}
          <div className="mt-6 flex items-start gap-3 rounded-2xl border border-[#DDE9DF] bg-[#DDE9DF]/25 p-4 text-xs text-[#183F32]">
            <ShieldAlert className="mt-0.5 size-4 shrink-0 text-[#397454]" />
            <div>
              <span className="font-semibold">Deterministic Stage Safety Gate:</span>{' '}
              <span>{currentStep.safetyCheck}</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

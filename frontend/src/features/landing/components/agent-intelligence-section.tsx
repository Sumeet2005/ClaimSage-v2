import { useState } from 'react'
import {
  Cpu,
  FileSearch,
  Layers,
  Scale,
  Wrench,
  AlertTriangle,
  FileCheck2,
  CheckCircle,
  ShieldCheck,
  ChevronRight,
} from 'lucide-react'
import { CLAIM_AGENTS } from '../data/agent-data'
import { Badge } from '@/components/ui/badge'

export function AgentIntelligenceSection() {
  const [selectedAgentId, setSelectedAgentId] = useState<string>('supervisor')
  const [activeTab, setActiveTab] = useState<'contract' | 'rules' | 'payload'>('contract')
  const [jsonView, setJsonView] = useState<'formatted' | 'raw'>('formatted')

  const agentIcons: Record<string, typeof Cpu> = {
    supervisor: Cpu,
    intake: FileSearch,
    evidence: Layers,
    policy: Scale,
    repair: Wrench,
    risk: AlertTriangle,
    review_report: FileCheck2,
  }

  const fallbackAgent = CLAIM_AGENTS[0]!
  const selectedAgent =
    CLAIM_AGENTS.find((a) => a.id === selectedAgentId) ?? fallbackAgent
  const Icon = agentIcons[selectedAgent.id] ?? Cpu

  return (
    <section id="agents" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
              Signature System
            </p>
            <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
              Six specialist agents. One cohesive LangGraph supervisor.
            </h2>
            <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
              Every agent operates under a rigid Pydantic contract, consuming verified upstream evidence chunks and enforcing deterministic safety rules before emitting state transitions.
            </p>
          </div>

          <div className="flex items-center gap-2 rounded-2xl border border-[#E9E5DB] bg-white p-3 text-xs text-[#6F7770]">
            <ShieldCheck className="size-4 text-[#397454]" />
            <span>Pre-invocation token budgeted & schema validated</span>
          </div>
        </div>

        {/* Main Interactive Studio Grid */}
        <div className="mt-12 grid gap-8 lg:grid-cols-12">
          {/* Agent Navigation List */}
          <div className="lg:col-span-4 flex flex-col gap-2">
            <p className="px-2 text-xs font-semibold text-[#6F7770] uppercase tracking-wider">
              Specialist Mesh
            </p>

            <div className="space-y-1.5">
              {CLAIM_AGENTS.map((agent) => {
                const AgentIcon = agentIcons[agent.id] ?? Cpu
                const isSelected = agent.id === selectedAgentId
                const isSupervisor = agent.id === 'supervisor'

                return (
                  <button
                    key={agent.id}
                    type="button"
                    onClick={() => setSelectedAgentId(agent.id)}
                    className={`flex w-full items-center justify-between rounded-2xl p-3.5 text-left transition-all duration-200 border ${
                      isSelected
                        ? 'border-[#183F32] bg-[#183F32] text-white shadow-sm'
                        : 'border-[#E9E5DB] bg-white text-[#18211D] hover:bg-[#FAF9F6] hover:border-[#DDE9DF]'
                    }`}
                  >
                    <div className="flex items-center gap-3">
                      <span
                        className={`grid size-9 place-items-center rounded-xl ${
                          isSelected
                            ? 'bg-[#245744] text-white'
                            : isSupervisor
                              ? 'bg-[#183F32] text-white'
                              : 'bg-[#FAF9F6] text-[#183F32] border border-[#E9E5DB]'
                        }`}
                      >
                        <AgentIcon className="size-4.5" />
                      </span>
                      <div>
                        <div className="flex items-center gap-2">
                          <p className="font-display text-sm font-semibold">{agent.name}</p>
                          {isSupervisor && (
                            <span className="rounded bg-[#EDE7D9] px-1.5 py-0.2 text-[9px] font-bold text-[#183F32] uppercase">
                              Graph Head
                            </span>
                          )}
                        </div>
                        <p
                          className={`text-xs truncate max-w-[200px] ${
                            isSelected ? 'text-[#EDE7D9]' : 'text-[#6F7770]'
                          }`}
                        >
                          {agent.sourceFile}
                        </p>
                      </div>
                    </div>

                    <ChevronRight
                      className={`size-4 transition-transform ${
                        isSelected ? 'text-white translate-x-0.5' : 'text-[#6F7770]'
                      }`}
                    />
                  </button>
                )
              })}
            </div>
          </div>

          {/* Agent Inspector Stage */}
          <div className="lg:col-span-8 rounded-3xl border border-[#E9E5DB] bg-white p-6 sm:p-8 shadow-sm">
            {/* Header */}
            <div className="flex flex-wrap items-start justify-between gap-4 border-b border-[#E9E5DB] pb-6">
              <div className="flex items-center gap-4">
                <span className="grid size-12 place-items-center rounded-2xl bg-[#183F32] text-white shadow-sm">
                  <Icon className="size-6" />
                </span>
                <div>
                  <div className="flex items-center gap-3">
                    <h3 className="font-display text-2xl font-semibold text-[#18211D]">
                      {selectedAgent.name}
                    </h3>
                    <code className="rounded-md border border-[#E9E5DB] bg-[#FAF9F6] px-2 py-0.5 font-mono text-xs text-[#397454]">
                      {selectedAgent.sourceFile}
                    </code>
                  </div>
                  <p className="mt-1 text-sm text-[#6F7770]">{selectedAgent.role}</p>
                </div>
              </div>

              <div className="flex items-center gap-2">
                <Badge variant="default" className="bg-[#DDE9DF] text-[#183F32] border-none font-semibold">
                  Step #{selectedAgent.executionOrder} in Pipeline
                </Badge>
              </div>
            </div>

            {/* Key Responsibilities */}
            <div className="mt-6">
              <p className="text-xs font-semibold uppercase tracking-wider text-[#6F7770]">
                Core Responsibilities
              </p>
              <div className="mt-3 grid gap-2.5 sm:grid-cols-2">
                {selectedAgent.keyResponsibilities.map((resp, i) => (
                  <div
                    key={i}
                    className="flex items-start gap-2.5 rounded-xl border border-[#E9E5DB] bg-[#FAF9F6] p-3 text-xs leading-relaxed text-[#18211D]"
                  >
                    <CheckCircle className="mt-0.5 size-3.5 shrink-0 text-[#397454]" />
                    <span>{resp}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Input Dependencies */}
            <div className="mt-6">
              <p className="text-xs font-semibold uppercase tracking-wider text-[#6F7770]">
                Input Stream Requirements
              </p>
              <div className="mt-2 flex flex-wrap gap-2">
                {selectedAgent.inputDependencies.map((dep, i) => (
                  <span
                    key={i}
                    className="rounded-lg border border-[#E9E5DB] bg-white px-2.5 py-1 text-xs font-medium text-[#18211D]"
                  >
                    • {dep}
                  </span>
                ))}
              </div>
            </div>

            {/* Sub-tab navigation */}
            <div className="mt-8 flex items-center justify-between border-b border-[#E9E5DB] pb-3">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setActiveTab('contract')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeTab === 'contract'
                      ? 'bg-[#183F32] text-white'
                      : 'text-[#6F7770] hover:text-[#18211D] hover:bg-[#FAF9F6]'
                  }`}
                >
                  Pydantic Contract Schema
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('rules')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeTab === 'rules'
                      ? 'bg-[#183F32] text-white'
                      : 'text-[#6F7770] hover:text-[#18211D] hover:bg-[#FAF9F6]'
                  }`}
                >
                  Deterministic Guardrails
                </button>
                <button
                  type="button"
                  onClick={() => setActiveTab('payload')}
                  className={`rounded-lg px-3 py-1.5 text-xs font-semibold transition-colors ${
                    activeTab === 'payload'
                      ? 'bg-[#183F32] text-white'
                      : 'text-[#6F7770] hover:text-[#18211D] hover:bg-[#FAF9F6]'
                  }`}
                >
                  Sample Output Payload
                </button>
              </div>

              {activeTab === 'payload' && (
                <div className="flex items-center gap-1 rounded-md border border-[#E9E5DB] bg-[#FAF9F6] p-0.5 text-[11px]">
                  <button
                    type="button"
                    onClick={() => setJsonView('formatted')}
                    className={`rounded px-2 py-0.5 ${
                      jsonView === 'formatted' ? 'bg-white font-semibold text-[#183F32]' : 'text-[#6F7770]'
                    }`}
                  >
                    Formatted
                  </button>
                  <button
                    type="button"
                    onClick={() => setJsonView('raw')}
                    className={`rounded px-2 py-0.5 ${
                      jsonView === 'raw' ? 'bg-white font-semibold text-[#183F32]' : 'text-[#6F7770]'
                    }`}
                  >
                    Raw JSON
                  </button>
                </div>
              )}
            </div>

            {/* Tab content area */}
            <div className="mt-4">
              {activeTab === 'contract' && (
                <div className="rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-4">
                  <div className="flex items-center justify-between text-xs font-semibold text-[#6F7770]">
                    <span>Contract Interface</span>
                    <span className="font-mono text-[#397454]">Pydantic v2 BaseOutput</span>
                  </div>
                  <pre className="mt-3 overflow-x-auto rounded-xl bg-white p-4 font-mono text-xs text-[#18211D] border border-[#E9E5DB] leading-relaxed">
                    <code>{`class ${selectedAgent.contract.split('(')[0]}(BaseModel):
    # Schema extracted from backend/src/claimsage/agents/${selectedAgent.sourceFile}
    # Enforces strict validation and citation anchoring
    ${selectedAgent.contract}`}</code>
                  </pre>
                </div>
              )}

              {activeTab === 'rules' && (
                <div className="space-y-3">
                  {selectedAgent.deterministicRules.map((rule, idx) => (
                    <div
                      key={idx}
                      className="flex items-start gap-3 rounded-2xl border border-[#DDE9DF] bg-[#DDE9DF]/20 p-4 text-xs leading-relaxed text-[#18211D]"
                    >
                      <ShieldCheck className="mt-0.5 size-4 shrink-0 text-[#183F32]" />
                      <div>
                        <p className="font-semibold text-[#183F32]">Deterministic Constraint #{idx + 1}</p>
                        <p className="mt-0.5 text-[#6F7770]">{rule}</p>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {activeTab === 'payload' && (
                <div className="rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-4">
                  {jsonView === 'raw' ? (
                    <pre className="max-h-[280px] overflow-auto rounded-xl bg-white p-4 font-mono text-xs text-[#18211D] border border-[#E9E5DB] leading-relaxed">
                      <code>{JSON.stringify(selectedAgent.samplePayload.rawJson, null, 2)}</code>
                    </pre>
                  ) : (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between rounded-xl bg-white p-3 border border-[#E9E5DB] text-xs">
                        <span className="text-[#6F7770]">Execution Status:</span>
                        <span className="font-semibold text-[#397454] capitalize">
                          {selectedAgent.samplePayload.status}
                        </span>
                      </div>
                      <div className="flex items-center justify-between rounded-xl bg-white p-3 border border-[#E9E5DB] text-xs">
                        <span className="text-[#6F7770]">Anchor Citations Bound:</span>
                        <span className="font-semibold text-[#18211D]">
                          {selectedAgent.samplePayload.citationsCount} source chunks
                        </span>
                      </div>
                      <div className="rounded-xl bg-white p-3 border border-[#E9E5DB] text-xs">
                        <span className="font-semibold text-[#18211D]">Findings Summary:</span>
                        <p className="mt-1 text-[#6F7770]">{selectedAgent.samplePayload.findingsSummary}</p>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

import { useState } from 'react'
import { Container } from 'lucide-react'

export function ArchitectureSection() {
  const [selectedService, setSelectedService] = useState<string>('backend')

  const services = [
    {
      id: 'frontend',
      name: 'claimsage-frontend',
      role: 'Client Interface & Nginx Reverse Proxy',
      tech: 'React 19, TypeScript, Vite 8, Tailwind CSS v4, Nginx 1.27',
      port: ':8080 (Public)',
      protocol: 'HTTP / REST',
      description:
        'Single-page application compiled to optimized static assets and served via Alpine Nginx. Reverse-proxies /api/ and /health/ requests directly to the FastAPI service.',
    },
    {
      id: 'backend',
      name: 'claimsage-backend',
      role: 'FastAPI Core REST API',
      tech: 'Python 3.12, FastAPI 0.115+, Pydantic v2, SQLAlchemy 2.0',
      port: ':8000 (Internal)',
      protocol: 'HTTP / JSON',
      description:
        'Mounts authenticated REST endpoints under /api/v1 for claims, versioned policies, investigation queue dispatch, and audit logging. Connects to PostgreSQL via psycopg3.',
    },
    {
      id: 'worker',
      name: 'claimsage-worker',
      role: 'Asynchronous LangGraph Runner',
      tech: 'LangGraph, PostgreSQL Leases (SKIP LOCKED), Python 3.12',
      port: 'Background Task Daemon',
      protocol: 'DB Advisory Locking',
      description:
        'Autonomous worker process polling the investigation_runs table. Acquires row leases using FOR UPDATE SKIP LOCKED and coordinates the multi-agent graph with heartbeats.',
    },
    {
      id: 'database',
      name: 'claimsage-db',
      role: 'Relational & Vector Storage',
      tech: 'PostgreSQL 16 + pgvector Extension',
      port: ':5432 (Internal)',
      protocol: 'TCP / PostgreSQL Wire',
      description:
        'Houses relational schemas for users, claims, and versioned policies alongside 384-dimensional dense vectors (HNSW index) and tsvector lexical inverted indexes.',
    },
    {
      id: 'minio',
      name: 'claimsage-minio',
      role: 'S3-Compatible Object Storage',
      tech: 'MinIO Object Server',
      port: ':9000 API / :9001 Web Console',
      protocol: 'S3 API / AWS SigV4',
      description:
        'Stores raw claim documents, scanned hospital bills, and official insurer policy PDFs with SHA-256 cryptographic checksums.',
    },
    {
      id: 'llm',
      name: 'Cloud LLM Layer',
      role: 'Specialist Reasoning & Synthesis',
      tech: 'Groq Cloud (Primary) + Google Gemini (Configured Fallback)',
      port: 'HTTPS Cloud Endpoints',
      protocol: 'TLS / REST',
      description:
        'Groq Cloud serves as the verified primary execution engine running gpt-oss-120b. Google Gemini is configured as the fallback provider adapter in llm.py when rate limits occur.',
    },
  ]

  const fallbackService = services[1]!
  const active = services.find((s) => s.id === selectedService) ?? fallbackService

  return (
    <section id="architecture" className="border-b border-[#E9E5DB] bg-[#FAF9F6] py-16 sm:py-24">
      <div className="mx-auto max-w-[1400px] px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="max-w-2xl">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-[#397454]">
            Technical Blueprint
          </p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.03em] text-[#18211D] sm:text-4xl">
            Container topology & production architecture.
          </h2>
          <p className="mt-4 text-base leading-relaxed text-[#6F7770]">
            An isolated, microservice-based architecture deployed seamlessly via Docker Compose with zero external state dependencies.
          </p>
        </div>

        {/* Architecture Topology Grid */}
        <div className="mt-12 grid gap-6 lg:grid-cols-12">
          {/* Services Selector */}
          <div className="lg:col-span-5 space-y-2">
            <p className="px-2 text-xs font-semibold uppercase tracking-wider text-[#6F7770]">
              Container Topology (claimsage-network)
            </p>

            {services.map((svc) => (
              <button
                key={svc.id}
                type="button"
                onClick={() => setSelectedService(svc.id)}
                className={`flex w-full items-center justify-between rounded-2xl p-4 text-left transition-all border ${
                  selectedService === svc.id
                    ? 'border-[#183F32] bg-[#183F32] text-white shadow-xs'
                    : 'border-[#E9E5DB] bg-white text-[#18211D] hover:bg-[#FAF9F6]'
                }`}
              >
                <div>
                  <div className="flex items-center gap-2">
                    <p className="font-mono text-xs font-semibold">{svc.name}</p>
                    <span
                      className={`rounded px-1.5 py-0.2 text-[10px] font-mono ${
                        selectedService === svc.id
                          ? 'bg-[#245744] text-[#EDE7D9]'
                          : 'bg-[#FAF9F6] text-[#397454] border border-[#E9E5DB]'
                      }`}
                    >
                      {svc.port}
                    </span>
                  </div>
                  <p
                    className={`mt-0.5 text-xs truncate max-w-[280px] ${
                      selectedService === svc.id ? 'text-[#EDE7D9]' : 'text-[#6F7770]'
                    }`}
                  >
                    {svc.role}
                  </p>
                </div>
              </button>
            ))}
          </div>

          {/* Service Blueprint Card */}
          <div className="lg:col-span-7 flex flex-col justify-between rounded-3xl border border-[#E9E5DB] bg-white p-6 sm:p-8 shadow-sm">
            <div>
              <div className="flex items-center justify-between border-b border-[#E9E5DB] pb-4">
                <div>
                  <code className="rounded-md bg-[#FAF9F6] px-2.5 py-1 font-mono text-xs font-semibold text-[#183F32] border border-[#E9E5DB]">
                    {active.name}
                  </code>
                  <h3 className="mt-2 font-display text-2xl font-semibold text-[#18211D]">
                    {active.role}
                  </h3>
                </div>
                <span className="rounded-full bg-[#DDE9DF] px-3 py-1 font-mono text-xs font-semibold text-[#183F32]">
                  {active.port}
                </span>
              </div>

              <p className="mt-6 text-sm leading-relaxed text-[#6F7770]">
                {active.description}
              </p>

              <div className="mt-6 rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-4">
                <p className="text-xs font-semibold text-[#6F7770] uppercase tracking-wider">
                  Verified Technology Stack
                </p>
                <p className="mt-1 font-mono text-xs text-[#18211D] font-medium">
                  {active.tech}
                </p>
              </div>

              <div className="mt-4 rounded-2xl border border-[#E9E5DB] bg-[#FAF9F6] p-4">
                <p className="text-xs font-semibold text-[#6F7770] uppercase tracking-wider">
                  Internal Communication Protocol
                </p>
                <p className="mt-1 font-mono text-xs text-[#397454] font-medium">
                  {active.protocol}
                </p>
              </div>
            </div>

            <div className="mt-8 flex items-center gap-2 text-xs text-[#6F7770] border-t border-[#E9E5DB] pt-4">
              <Container className="size-4 text-[#397454]" />
              <span>Full Docker Compose orchestration with healthcheck auto-restart</span>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}

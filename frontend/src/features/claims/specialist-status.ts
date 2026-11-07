const SPECIALIST_FIELDS = [
  ['intake_analysis', 'Intake Agent', 'intake_analysis_status'],
  ['evidence_analysis', 'Evidence Analyst', 'evidence_analysis_status'],
  ['policy_analysis', 'Policy Analyst', 'ai_analysis_status'],
  [
    'repair_estimate_analysis',
    'Repair Estimate Analyst',
    'repair_estimate_analysis_status',
  ],
  ['risk_analysis', 'Risk & Anomaly Agent', 'risk_analysis_status'],
] as const

export function getSpecialistResults(result: Record<string, unknown>) {
  return SPECIALIST_FIELDS.flatMap(([field, title, statusField]) => {
    const output = result[field]
    const status = result[statusField]

    return output !== undefined || status !== undefined
      ? [{ field, title, status, output }]
      : []
  })
}

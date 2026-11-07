import assert from 'node:assert/strict'
import { test } from 'node:test'
import { getSpecialistResults } from '../src/features/claims/specialist-status.ts'

test('Policy Analyst status uses the backend ai_analysis_status field', () => {
  for (const status of ['completed', 'unavailable', 'skipped']) {
    const policyAnalyst = getSpecialistResults({
      ai_analysis_status: status,
    }).find(({ field }) => field === 'policy_analysis')

    assert.ok(policyAnalyst)
    assert.equal(policyAnalyst.status, status)
  }
})

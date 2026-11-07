import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { isAxiosError } from 'axios'
import { AlertCircle, Loader2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { createClaim } from '@/features/claims/claims-api'
import { claimsQueryKey } from '@/features/claims/use-claims'

interface CreateClaimDialogProps {
  isOpen: boolean
  onClose: () => void
}

export function CreateClaimDialog({ isOpen, onClose }: CreateClaimDialogProps) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const [claimNumber, setClaimNumber] = useState('')
  const [claimantName, setClaimantName] = useState('')
  const [claimType, setClaimType] = useState('health')
  const [policyIdentifier, setPolicyIdentifier] = useState('')
  const [lossDate, setLossDate] = useState('')
  const [summary, setSummary] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  if (!isOpen) return null

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)

    if (!claimNumber.trim()) {
      setError('Claim number is required.')
      return
    }
    if (!claimantName.trim()) {
      setError('Claimant name is required.')
      return
    }

    setIsSubmitting(true)
    try {
      const claim = await createClaim({
        claim_number: claimNumber.trim(),
        claimant_name: claimantName.trim(),
        claim_type: claimType,
        policy_identifier: policyIdentifier.trim() || undefined,
        loss_date: lossDate || undefined,
        summary: summary.trim() || undefined,
      })

      await queryClient.invalidateQueries({ queryKey: claimsQueryKey })
      onClose()
      navigate(`/claims/${claim.id}`)
    } catch (err: unknown) {
      if (isAxiosError<{ detail?: string }>(err)) {
        setError(err.response?.data?.detail ?? 'Failed to create claim.')
      } else {
        setError('An unexpected error occurred.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-graphite-950/60 p-4 backdrop-blur-sm"
      role="dialog"
    >
      <Card className="relative w-full max-w-lg border-ivory-300 bg-white p-6 shadow-2xl">
        <div className="flex items-center justify-between border-b border-ivory-200 pb-4">
          <div>
            <h2 className="font-display text-lg font-bold text-graphite-900">
              New Insurance Claim
            </h2>
            <p className="mt-1 text-xs text-graphite-500">
              Register a first notice of loss (FNOL) or new claim record.
            </p>
          </div>
          <button
            aria-label="Close dialog"
            className="rounded-lg p-1 text-graphite-400 hover:bg-ivory-100 hover:text-graphite-700"
            onClick={onClose}
            type="button"
          >
            <X className="size-5" />
          </button>
        </div>

        {error && (
          <div className="mt-4 flex items-center gap-2 rounded-lg bg-rose-50 p-3 text-xs text-rose-700">
            <AlertCircle className="size-4 shrink-0 text-rose-500" />
            <span>{error}</span>
          </div>
        )}

        <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs font-semibold text-graphite-700" htmlFor="new-claim-number">
                Claim Number *
              </Label>
              <Input
                className="mt-1 h-9 bg-white text-xs"
                id="new-claim-number"
                onChange={(e) => setClaimNumber(e.target.value)}
                placeholder="e.g. CLM-2026-001"
                required
                value={claimNumber}
              />
            </div>
            <div>
              <Label className="text-xs font-semibold text-graphite-700" htmlFor="new-claim-type">
                Claim Type *
              </Label>
              <select
                className="mt-1 h-9 w-full rounded-md border border-ivory-300 bg-white px-2 text-xs text-graphite-800 focus:outline-none focus:ring-2 focus:ring-emerald/40"
                id="new-claim-type"
                onChange={(e) => setClaimType(e.target.value)}
                value={claimType}
              >
                <option value="health">Health Insurance</option>
                <option value="auto">Auto Insurance</option>
                <option value="property">Property Insurance</option>
              </select>
            </div>
          </div>

          <div>
            <Label className="text-xs font-semibold text-graphite-700" htmlFor="new-claimant-name">
              Claimant Name *
            </Label>
            <Input
              className="mt-1 h-9 bg-white text-xs"
              id="new-claimant-name"
              onChange={(e) => setClaimantName(e.target.value)}
              placeholder="e.g. Ananya Mehta"
              required
              value={claimantName}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs font-semibold text-graphite-700" htmlFor="new-policy-id">
                Policy Identifier
              </Label>
              <Input
                className="mt-1 h-9 bg-white text-xs"
                id="new-policy-id"
                onChange={(e) => setPolicyIdentifier(e.target.value)}
                placeholder="e.g. STAR-HEALTH-001"
                value={policyIdentifier}
              />
            </div>
            <div>
              <Label className="text-xs font-semibold text-graphite-700" htmlFor="new-loss-date">
                Loss Date
              </Label>
              <Input
                className="mt-1 h-9 bg-white text-xs"
                id="new-loss-date"
                onChange={(e) => setLossDate(e.target.value)}
                type="date"
                value={lossDate}
              />
            </div>
          </div>

          <div>
            <Label className="text-xs font-semibold text-graphite-700" htmlFor="new-summary">
              Claim Summary / Medical Reason
            </Label>
            <textarea
              className="mt-1 w-full rounded-md border border-ivory-300 bg-white p-2 text-xs text-graphite-800 placeholder:text-graphite-400 focus:outline-none focus:ring-2 focus:ring-emerald/40"
              id="new-summary"
              onChange={(e) => setSummary(e.target.value)}
              placeholder="e.g. Inpatient surgical treatment for appendectomy."
              rows={3}
              value={summary}
            />
          </div>

          <div className="flex justify-end gap-2 border-t border-ivory-200 pt-4">
            <Button
              disabled={isSubmitting}
              onClick={onClose}
              type="button"
              variant="outline"
            >
              Cancel
            </Button>
            <Button disabled={isSubmitting} type="submit">
              {isSubmitting ? (
                <>
                  <Loader2 className="mr-1.5 size-4 animate-spin" />
                  Creating...
                </>
              ) : (
                'Create Claim'
              )}
            </Button>
          </div>
        </form>
      </Card>
    </div>
  )
}

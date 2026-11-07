export interface Claim {
  id: string
  claim_number: string
  claimant_name: string
  claim_type: string
  status: string
  team_id: string | null
  summary: string | null
  created_at: string
  policy_identifier: string | null
  insurer_name: string | null
  product_name: string | null
  loss_date: string | null
}

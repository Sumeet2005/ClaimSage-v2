export interface RagQueryPreset {
  id: string
  label: string
  claimType: 'health' | 'motor'
  queryText: string
  denseTopMatch: {
    chunkId: string
    sourceDoc: string
    page: number
    rank: number
    similarity: number
    snippet: string
  }
  sparseTopMatch: {
    chunkId: string
    sourceDoc: string
    page: number
    rank: number
    tsRankScore: number
    snippet: string
  }
  fusedTopResult: {
    chunkId: string
    sourceDoc: string
    page: number
    rrfScore: number
    verbatimQuote: string
    clauseRef: string
    rationale: string
  }
}

export const RAG_PRESETS: RagQueryPreset[] = [
  {
    id: 'room-rent',
    label: 'Room Rent Sub-Limit Capping',
    claimType: 'health',
    queryText: 'What is the daily room rent capping and proportionate deduction clause for Plan Gold?',
    denseTopMatch: {
      chunkId: 'pol-chunk-041',
      sourceDoc: 'Synthetic_Health_Insurance_Policy_v3.pdf',
      page: 12,
      rank: 1,
      similarity: 0.892,
      snippet: 'Clause 4.1: Room, boarding expenses incurred at hospital up to 1% of Sum Insured per day. If insured occupies room higher than limit, proportionate deduction applies.',
    },
    sparseTopMatch: {
      chunkId: 'pol-chunk-041',
      sourceDoc: 'Synthetic_Health_Insurance_Policy_v3.pdf',
      page: 12,
      rank: 1,
      tsRankScore: 0.941,
      snippet: 'Room rent capping clause: daily room and boarding charges payable up to 1% of the Sum Insured per day. ICU expenses capped at 2% of Sum Insured per day.',
    },
    fusedTopResult: {
      chunkId: 'pol-chunk-041',
      sourceDoc: 'Synthetic_Health_Insurance_Policy_v3.pdf',
      page: 12,
      rrfScore: 0.0328, // 1/(60+1) + 1/(60+1) = 2/61 ≈ 0.03278
      verbatimQuote: 'Room, boarding, and nursing expenses incurred at the hospital up to 1% of the Sum Insured per day, subject to a maximum of INR 5,000 per day. ICU charges are payable up to 2% of the Sum Insured per day.',
      clauseRef: 'Section 4, Clause 4.1 (Room Rent & ICU Sub-limits)',
      rationale: 'RRF ranked pol-chunk-041 as #1 in both dense cosine (0.892) and sparse BM25 text rank (0.941). Fused score 0.0328 confirmed unanimous agreement.',
    },
  },
  {
    id: 'ped-waiting',
    label: 'Pre-Existing Disease Waiting Period',
    claimType: 'health',
    queryText: 'Does pre-existing hypertension and diabetes require a 36-month continuous waiting period?',
    denseTopMatch: {
      chunkId: 'pol-chunk-088',
      sourceDoc: 'Synthetic_Health_Insurance_Policy_v3.pdf',
      page: 19,
      rank: 1,
      similarity: 0.874,
      snippet: 'Clause 4.8 Pre-Existing Diseases (PED): Covered after thirty-six (36) months of continuous coverage without break from the policy inception date.',
    },
    sparseTopMatch: {
      chunkId: 'pol-chunk-089',
      sourceDoc: 'Synthetic_Health_Insurance_Policy_v3.pdf',
      page: 20,
      rank: 2,
      tsRankScore: 0.825,
      snippet: 'Specified disease waiting periods: Hypertension, Diabetes, and associated cardiovascular ailments are covered post completion of 36 months of continuous coverage.',
    },
    fusedTopResult: {
      chunkId: 'pol-chunk-088',
      sourceDoc: 'Synthetic_Health_Insurance_Policy_v3.pdf',
      page: 19,
      rrfScore: 0.0325,
      verbatimQuote: 'Benefits will not be available for any Pre-existing Condition until 36 consecutive months of continuous coverage have elapsed since the inception date of the first policy with the insurer.',
      clauseRef: 'Section 4, Clause 4.8 (Pre-Existing Disease Exclusion)',
      rationale: 'Dense search surfaced pol-chunk-088 (#1 rank) while lexical search positioned it as #2. Fused RRF cleanly surfaced canonical waiting period definition.',
    },
  },
  {
    id: 'depreciation-rate',
    label: 'Plastic & Rubber Parts Depreciation',
    claimType: 'motor',
    queryText: 'What is the depreciation percentage schedule applicable for plastic bumper replacement?',
    denseTopMatch: {
      chunkId: 'pol-chunk-114',
      sourceDoc: 'Synthetic_Motor_Insurance_Policy_v1.pdf',
      page: 7,
      rank: 1,
      similarity: 0.915,
      snippet: 'Depreciation on parts for partial loss claims: For all rubber, nylon, and plastic parts, tyres, tubes, and batteries: 50% depreciation deduction shall be applied.',
    },
    sparseTopMatch: {
      chunkId: 'pol-chunk-114',
      sourceDoc: 'Synthetic_Motor_Insurance_Policy_v1.pdf',
      page: 7,
      rank: 1,
      tsRankScore: 0.963,
      snippet: 'Schedule of depreciation: Plastic, rubber parts, batteries 50%; Glass parts Nil depreciation; Fibre glass components 30%.',
    },
    fusedTopResult: {
      chunkId: 'pol-chunk-114',
      sourceDoc: 'Synthetic_Motor_Insurance_Policy_v1.pdf',
      page: 7,
      rrfScore: 0.0328,
      verbatimQuote: 'For all rubber, nylon and plastic parts, tyres and tubes, batteries and airbags, a fixed rate of fifty percent (50%) depreciation shall be deducted from the replacement part invoice price.',
      clauseRef: 'Section 1, Clause 1.4 (Depreciation on Replacement Parts)',
      rationale: 'Unanimous rank-1 agreement across dense vector and sparse lexical index ensures exact arithmetic parameter for repair_estimate_rules.py.',
    },
  },
]

// lib/types.ts — TypeScript types matching backend schemas exactly

export type RulingDecision = 'PERMITTED' | 'NOT_PERMITTED' | 'NEEDS_CLARIFICATION' | 'SERVICE_UNAVAILABLE'
export type RemediationType = 'WAIVER' | 'SIMULATION'
export type ClauseType = 'PERMISSION' | 'RESTRICTION' | 'EXCEPTION' | 'OVERRIDE' | 'WAIVER' | 'DEFINITION' | 'PROCEDURE' | 'RULE' | 'OTHER'
export type RelationshipType = 'SUPERSEDES' | 'OVERRIDE' | 'EXCEPTION_TO' | 'REFERENCES' | 'CONFLICTS_WITH' | 'EXTENDS' | 'DERIVED_FROM'
export type ScanSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO'
export type CheckerStatus = 'PASS' | 'REVISE' | 'CHECK_UNAVAILABLE'
export type PrecedentStatus = 'CONSISTENT' | 'INCONSISTENT' | 'NO_RELEVANT_PRECEDENT' | 'CHECK_UNAVAILABLE'
export type AnalysisStatus = 'SUCCESS' | 'NO_ELIGIBLE_CASES' | 'CHECK_UNAVAILABLE' | 'FAILED'

export interface PolicyContext {
  region?: string
  department?: string
  vendor?: string
  dataset?: string
  user_role?: string
  additional_context?: Record<string, unknown>
}

export interface IdentityContext {
  user_id: string
  display_name: string
  vendor: string
  region: string
  department: string
  role: string
  permissions: string[]
  status: string
  session_token?: string
}

export interface Citation {
  policy_id: string
  policy_title: string
  section_id?: string
  clause_type?: ClauseType
  text_excerpt: string
  relevance_score?: number
}

export interface BlockingClause {
  policy_id: string
  policy_title: string
  section_id?: string
  text: string
}

export interface Ruling {
  ruling_id: string
  question: string
  context: PolicyContext
  decision: RulingDecision
  explanation: string
  citations: Citation[]
  relevant_policy_ids: string[]
  confidence: number
  caveats: string[]
  blocking_clause?: BlockingClause
  deterministic: boolean
  timestamp: string
}

export interface ClarificationRequest {
  question: string
  missing_fields: string[]
  reason: string
  suggested_options: Record<string, string[]>
}

export interface CheckerResult {
  approved: boolean
  objections: string[]
  missed_exceptions: string[]
  wrong_scope_flags: string[]
  false_premise_flags: string[]
  explanation: string
  round_number: number
  status: CheckerStatus
}

export interface StoredPrecedent {
  ruling_id: string
  question: string
  context: PolicyContext
  decision: RulingDecision
  explanation: string
  citations: Citation[]
  relevant_policy_ids: string[]
  timestamp: string
}

export interface PrecedentResult {
  has_precedent: boolean
  matches: StoredPrecedent[]
  is_consistent?: boolean | null
  discrepancy_explanation?: string
  consistency_explanation?: string
  status: PrecedentStatus
}

export interface SensitivityFlip {
  field: string
  original_value?: string
  new_value: string
  original_decision: RulingDecision
  new_decision: RulingDecision
  explanation: string
}

export interface SensitivityResult {
  ruling_id: string
  flips: SensitivityFlip[]
  nearest_flip?: SensitivityFlip
  is_fragile: boolean
  summary: string
  total_perturbations_tested: number
  status: AnalysisStatus
}

export interface RemediationStep {
  step_number: number
  description: string
  required_approval?: string
}

export interface RemediationResult {
  ruling_id: string
  remediation_type: RemediationType
  is_possible: boolean
  steps: RemediationStep[]
  required_approval?: string
  supporting_policy_ids: string[]
  supporting_section_ids: string[]
  hypothetical_change?: string
  explanation: string
}

export interface GraphNode {
  node_id: string
  node_type: string
  label: string
  policy_id?: string
  version?: string
  metadata: Record<string, unknown>
}

export interface GraphEdge {
  edge_id: string
  source_id: string
  target_id: string
  relationship_type: RelationshipType
  explanation?: string
  confidence: number
}

export interface ScanFinding {
  finding_id: string
  policy_id_a: string
  policy_title_a: string
  policy_id_b: string
  policy_title_b: string
  severity: ScanSeverity
  finding_type: string
  relationship_type?: RelationshipType
  description: string
  recommendation?: string
  is_landmine: boolean
}

export interface ScanResult {
  scan_id: string
  findings: ScanFinding[]
  landmines: ScanFinding[]
  total_policies_scanned: number
  summary: string
  timestamp: string
}

export interface SimulationChange {
  change_type: string
  target_policy_id?: string
  target_section_id?: string
  new_text?: string
  description: string
}

export interface SimulationImpact {
  question: string
  context: PolicyContext
  original_decision: RulingDecision
  hypothetical_decision: RulingDecision
  decision_changed: boolean
  original_explanation: string
  hypothetical_explanation: string
}

export interface SimulationResult {
  simulation_id: string
  change: SimulationChange
  total_questions_tested: number
  total_affected: number
  flipped_impacts: SimulationImpact[]
  unaffected_impacts: SimulationImpact[]
  impact_summary: string
  timestamp: string
  status: AnalysisStatus
}

export interface FinalResponse {
  session_id: string
  question: string
  context: PolicyContext
  ruling: Ruling
  checker_result?: CheckerResult
  clarification?: ClarificationRequest
  precedent?: PrecedentResult
  sensitivity?: SensitivityResult
  remediation?: RemediationResult
  graph_nodes: GraphNode[]
  graph_edges: GraphEdge[]
  agent_executions: AgentExecution[]
  processing_time_ms: number
  mode: string
}

export interface AgentExecution {
  agent: string
  outcome: string
  provider: string
  model?: string
  status: 'COMPLETED' | 'UNAVAILABLE' | string
  fallback_used: boolean
  calls: number
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  response?: FinalResponse
  simulationResult?: SimulationResult
  timestamp: Date
  isLoading?: boolean
}

export interface AskRequest {
  question: string
  context: PolicyContext
  as_of_date?: string
  session_id?: string
}

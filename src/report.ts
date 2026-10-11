export type Measurements = {
  model_calls: number | null
  tokens_in: number | null
  tokens_out: number | null
  cost_usd: number | null
  wall_time_seconds: number | null
}

export type SourceReference = { path: string; start_line: number; end_line: number }
export type Finding = {
  finding_id: string
  waste: string | null
  proposed_change: string | null
  behaviour_risk: string | null
  estimated_saving: { cost_usd: number | null; wall_time_seconds: number | null; tokens: number | null; model_calls: number | null; method: string } | null
  saving_scope: string | null
  source: SourceReference[]
  run_ids: string[]
}
export type MetricComparison = { baseline: number | null; candidate: number | null; change_percent: number | null }
export type Comparison = {
  verdict: string
  all_tasks: boolean
  variation_measured: boolean
  note: string
  totals: Record<keyof Measurements, MetricComparison>
  tasks: {
    task_id: string; name: string | null; baseline_status: string | null; candidate_status: string | null
    regressed: boolean; fixed: boolean; candidate_reason: string | null
    baseline_automatic_passes?: [number, number]; candidate_automatic_passes?: [number, number]
  }[]
}
export type Optimization = {
  job_id: string; status: string; decision: string | null; summary: string | null; incomplete: boolean; changed_files: string[]
  comparison: Comparison | null; comparison_is_of: string | null; patch_available: boolean; tried_patch_available: boolean
  trace?: { status: string; trace_id?: string; trace_ids?: string[]; reason?: string }
}
export type StageKind = 'onboarding' | 'baseline' | 'investigation' | 'optimization'
export type ActiveJob = { kind: StageKind; job_id: string; events?: string }
export type ImportReport = {
  import: { import_id: string; repository: string; branch: string; commit_sha: string }
  adapter: { sha256: string; job_id: string; created_at: number } | null
  baseline: {
    baseline_id?: string
    status: string; model: string | null; repetitions: number | null
    passed: number | null; failed: number | null; needs_review: number | null
    per_pass: Measurements
    tasks: (Measurements & { task_id: string | null; name: string | null; status: string | null; reason: string | null })[]
    note: string
  } | null
  investigation: { job_id?: string; status: string; summary: string | null; incomplete: boolean; nothing_worth_changing: boolean | null; findings: Finding[]; note: string } | null
  optimizations: Optimization[]
  accepted: string[]
  stages: { onboarded: boolean; baseline: boolean; investigated: boolean; optimized: boolean }
  next: { action: string; reason: string | null }
  active?: ActiveJob | null
  limits: string[]
}

export const steps = ['import', 'setup', 'baseline', 'findings', 'fix', 'result'] as const
export type Step = typeof steps[number]
export const stepNames: Record<Step, string> = { import: 'Import', setup: 'Setup', baseline: 'Baseline', findings: 'Findings', fix: 'Fix', result: 'Result' }

export function recommendedStep(report: ImportReport): Step {
  const action = report.next.action === 'wait' ? report.active?.kind : report.next.action
  switch (action) {
    case 'onboard': case 'onboarding': return 'setup'
    case 'baseline': return 'baseline'
    case 'investigate': case 'investigation': return 'findings'
    case 'optimize': case 'optimization': return 'fix'
    case 'review': return 'result'
    default: return 'import'
  }
}

export function measurement(value: number | null | undefined, unit: 'number' | 'usd' | 'seconds' = 'number'): string {
  if (value == null || !Number.isFinite(value)) return 'Not recorded'
  if (unit === 'usd') return `$${value.toLocaleString('en-US', { maximumSignificantDigits: 7 })}`
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 }) + (unit === 'seconds' ? ' s' : '')
}

export function barWidth(value: number | null, other: number | null): number {
  if (value == null || !Number.isFinite(value) || value < 0) return 0
  return value / Math.max(value, other != null && Number.isFinite(other) ? other : 0, 1e-12) * 100
}

export function sourceUrl(repository: string, commit: string, source: SourceReference): string | null {
  if (!/^[\w.-]+\/[\w.-]+$/.test(repository) || !/^[a-f0-9]{40}$/i.test(commit)
      || source.path.includes('\\') || source.path.split('/').some(part => !part || part === '.' || part === '..')
      || !Number.isInteger(source.start_line) || source.start_line < 1 || !Number.isInteger(source.end_line) || source.end_line < source.start_line) return null
  const path = source.path.split('/').map(encodeURIComponent).join('/')
  return `https://github.com/${repository}/blob/${commit}/${path}#L${source.start_line}${source.end_line === source.start_line ? '' : `-L${source.end_line}`}`
}

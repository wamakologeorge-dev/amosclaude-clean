interface ReportPayload {
  status: string
  repository: string
  reasoning: unknown
  plan: unknown
  patch: unknown
  shellResult: unknown
  deployment: unknown
  repositoryInfo: unknown
}

export function buildReport(payload: ReportPayload) {
  return {
    status: payload.status,
    repository: payload.repository,
    reasoning: payload.reasoning,
    plan: payload.plan,
    patch: payload.patch,
    shellResult: payload.shellResult,
    deployment: payload.deployment,
    repositoryInfo: payload.repositoryInfo,
  }
}

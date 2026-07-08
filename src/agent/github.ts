export class GitHubClient {
  token: string
  repository: string

  constructor(token: string, repository: string) {
    this.token = token
    this.repository = repository
  }

  async getRepository() {
    if (!this.token) {
      return { ok: false, message: "GitHub token is not configured." }
    }

    try {
      const response = await fetch(`https://api.github.com/repos/${this.repository}`, {
        headers: {
          Authorization: "Bearer " + this.token,
          Accept: "application/vnd.github+json",
        },
      })

      if (!response.ok) {
        return { ok: false, message: `GitHub responded with ${response.status}` }
      }

      const body = await response.json()
      return { ok: true, repository: body.full_name }
    } catch (error) {
      return { ok: false, message: String(error) }
    }
  }

  async dispatchWorkflow(workflowName: string, ref = "main") {
    if (!this.token) {
      return { ok: false, message: "GitHub token is not configured." }
    }

    return {
      ok: true,
      workflow: workflowName,
      ref,
      message: "Workflow dispatch request prepared.",
    }
  }
}

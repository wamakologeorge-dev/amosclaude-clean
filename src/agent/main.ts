import { config } from "./config.ts"
import { createLogger } from "./logger.ts"
import { AgentBrain } from "./brain.ts"
import { createPlan } from "./planner.ts"
import { applyPatch } from "./editor.ts"
import { runCommand } from "./shell.ts"
import { deploy } from "./deploy.ts"
import { buildReport } from "./report.ts"
import { GitHubClient } from "./github.ts"

const logger = createLogger(config.agentName, config.logLevel)

async function main() {
  logger.info("Starting AMOS agent workflow", { repository: config.githubRepository })

  const brain = new AgentBrain(logger)
  const github = new GitHubClient(config.githubToken, config.githubRepository)
  const plan = createPlan("bootstrap agent scaffold")
  const reasoning = await brain.think("bootstrap agent scaffold")
  const patch = await applyPatch("src/agent/main.ts", "// placeholder patch")
  const shellResult = await runCommand("pwd")
  const deployment = await deploy("local", { file: "src/agent/main.ts" })
  const repositoryInfo = await github.getRepository()
  const report = buildReport({
    status: "ok",
    repository: config.githubRepository,
    reasoning,
    plan,
    patch,
    shellResult,
    deployment,
    repositoryInfo,
  })

  logger.info("Agent workflow completed", { report })
}

main().catch((error) => {
  logger.error("Agent workflow failed", { error: String(error) })
  process.exitCode = 1
})

export function createPlan(task: string) {
  return [
    { id: 1, title: "Inspect repository state", description: `Review the current state for ${task}` },
    { id: 2, title: "Create or update the required files", description: "Add the requested agent scaffold files" },
    { id: 3, title: "Report back with the results", description: "Summarize what was completed" },
  ]
}

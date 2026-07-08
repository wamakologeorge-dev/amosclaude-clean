export async function applyPatch(filePath: string, content: string) {
  return {
    filePath,
    status: "stubbed",
    content,
  }
}

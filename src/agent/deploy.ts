export async function deploy(target: string, payload: Record<string, unknown>) {
  return {
    target,
    payload,
    status: "queued",
  }
}

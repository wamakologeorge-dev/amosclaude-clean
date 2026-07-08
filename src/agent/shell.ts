export async function runCommand(command: string, args: string[] = []) {
  return {
    command,
    args,
    output: `Command ${command} is ready to run.`,
  }
}

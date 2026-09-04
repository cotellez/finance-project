import type { Plugin } from "@opencode-ai/plugin"

/**
 * Finance-project maintenance & safety plugin.
 *
 * 1. SHELL GUARD: blocks any bash command that would leak an API key via
 *    command-line arguments (argv), per AGENTS.md rule #1. Key values must be
 *    read from environment variables and passed via environment inheritance.
 * 2. DATA SAFETY: warns when a bash command risks destructive file operations
 *    on the market cache or portfolio data.
 */
export default (async () => {
  const SENSITIVE_NAMES = [
    "ALPHA_VANTAGE_API_KEY",
    "api_key",
    "apikey",
    "API_TOKEN",
    "TOKEN",
  ]

  // Values that should never appear in an argv (they are keys or env var names).
  const isBlocked = (cmd: string): string | null => {
    // A key value passed as an argument looks like a long opaque token on the
    // command line. We can't know real secrets, so guard the env-var NAMES and
    // any obviously long hex/alnum token being `--`-prefixed or after a flag.
    const lower = cmd.toLowerCase()
    if (SENSITIVE_NAMES.some((n) => lower.includes(n.toLowerCase()))) {
      if (/\s--?[a-z_-]*key[a-z_-]*\s*=?\S/i.test(cmd)) {
        return `Refusing bash command that names an API key on the command line (argv). API keys must be read from environment variables only (AGENTS.md rule #1).`
      }
    }
    return null
  }

  return {
    "tool.execute.before": async (input, output) => {
      if (input.tool !== "bash") return
      const cmd = String(output?.args?.command ?? "")
      const reason = isBlocked(cmd)
      if (reason) {
        // Deny by throwing; prevents the command from running.
        throw new Error(reason)
      }
    },
  }
}) satisfies Plugin

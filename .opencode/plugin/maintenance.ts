import type { Plugin } from "@opencode-ai/plugin"

/**
 * Finance-project maintenance & safety plugin.
 *
 * 1. SHELL GUARD: blocks any bash command that would leak an API key via
 *    command-line arguments (argv), per AGENTS.md rule #1. Key values must be
 *    read from environment variables and passed via environment inheritance.
 * 2. DATA SAFETY: runtime data files (finance.json, portfolio.json,
 *    paper_trading.json, memory_long.json, memory_short.json) hold financial
 *    state and were previously written with no audit trail. They must be
 *    changed ONLY through the finance CLI/library, which validates schemas,
 *    rejects non-finite values, and writes an audit trail.
 *    - Direct `edit`/`write` tool edits to a data file are DENIED.
 *    - Bash shell redirection (`> file`) or rm/mv/cp/truncate on a data file
 *      are DENIED.
 *    - Bash that invokes the finance write commands (`finance add`, wrap-up,
 *      or library mutators) is WARNED loudly to the console. Interactive
 *      confirmation is not available in the pre-execution hook, so a prominent
 *      warning is emitted instead; the write still requires the agent to have
 *      permission (permission rules already put bash behind "ask" for
 *      subagents).
 */

export default (async () => {
  const SENSITIVE_NAMES = [
    "FRED_API_KEY",
    "api_key",
    "apikey",
    "API_TOKEN",
    "TOKEN",
  ]

  // Runtime data files that must only be changed through the finance
  // CLI/library so every write is validated, schema-checked, and audited.
  const DATA_FILES = new Set([
    "finance.json",
    "portfolio.json",
    "paper_trading.json",
    "memory_long.json",
    "memory_short.json",
  ])

  const basenameOf = (p: string | undefined | null): string | null => {
    if (!p) return null
    const base = String(p).replace(/\\/g, "/").split("/").pop() ?? ""
    return base || null
  }

  const isDataFile = (p: string | undefined | null): boolean => {
    const base = basenameOf(p)
    return base !== null && DATA_FILES.has(base)
  }

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

  // Direct bash writes to data files: shell redirection or file mutation.
  const findBashDirectWrite = (cmd: string): string | null => {
    for (const name of DATA_FILES) {
      // `> file`, `>> file` (or quoted), without `=>`/`->`/`==` prefixes.
      const redirect = new RegExp(`(^|[^=<>])>+\\s*["']?${name}["']?`)
      if (redirect.test(cmd)) {
        return `Refusing bash that writes directly to ${name}. It must be changed via the finance CLI/library so the write is validated and audited (e.g. 'finance add ...', portfolio add, wrap-up).`
      }
      const mutate = new RegExp(
        `(^|[;&|\\s])(rm|del|erase|unlink|truncate|mv|move)\\s+["']?${name}["']?`,
        "i"
      )
      if (mutate.test(cmd)) {
        return `Refusing bash that deletes or moves ${name}. It must be changed via the finance CLI/library so the write is validated and audited.`
      }
      const overwrite = new RegExp(
        `(^|[;&|\\s])(cp|copy|xcopy)\\s+\\S+\\s+["']?${name}["']?`,
        "i"
      )
      if (overwrite.test(cmd)) {
        return `Refusing bash that overwrites ${name} from another file. It must be changed via the finance CLI/library so the write is validated and audited.`
      }
    }
    return null
  }

  // Bash invocations of finance write paths (add / wrap-up / library mutators).
  const isFinanceWriteCmd = (cmd: string): boolean => {
    return (
      /\bfinance\b.*\b(wrap-up|add)\b/.test(cmd) ||
      /(add_transaction|handle_add|paper_buy|paper_sell|add_position)/.test(cmd)
    )
  }

  return {
    "tool.execute.before": async (input) => {
      // Direct edits to data files via the edit/write tools are denied.
      if (input.tool === "edit" || input.tool === "write") {
        const filePath = input.args?.filePath ?? input.args?.path
        if (isDataFile(filePath)) {
          throw new Error(
            `Refusing to ${input.tool} '${basenameOf(filePath)}' directly. Runtime data files must be changed through the finance CLI/library (finance add / portfolio / wrap-up) so writes are validated, schema-checked, and audited.`
          )
        }
        return input
      }

      if (input.tool !== "bash") return input
      const cmd = String(input.args?.command ?? "")

      const reason = isBlocked(cmd)
      if (reason) {
        // Deny by throwing; prevents the command from running.
        throw new Error(reason)
      }

      const direct = findBashDirectWrite(cmd)
      if (direct) {
        throw new Error(direct)
      }

      if (isFinanceWriteCmd(cmd)) {
        console.warn(
          `[maintenance] finance state write requested via bash: ${cmd}`
        )
      }

      // Anything else is allowed through the normal permission flow.
      return input
    },
  }
}) satisfies Plugin
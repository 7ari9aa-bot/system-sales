#!/usr/bin/env node
/**
 * The platform boundary, enforced by a script rather than by review.
 *
 * §2 of the mission: the React tree never calls `invoke()` and never calls
 * `fetch()`. ESLint bans the same things, but ESLint runs on files a developer
 * chose to lint; this runs on a directory tree and catches a file that never
 * made it into the config, a `// eslint-disable` added in haste, or a new
 * directory created next to the adapters.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join, posix, relative, resolve, win32 } from 'node:path'

const RULES = [
  'no-invoke',
  'no-fetch',
  'no-event-source',
  'no-web-storage',
  'no-tauri-import',
  'contract-no-any',
]

const CHECKS = [
  {
    rule: 'no-invoke',
    pattern: /\binvoke\s*\(/g,
    message: 'invoke() may only be called from src/platform/tauri/',
  },
  {
    rule: 'no-fetch',
    pattern: /\bfetch\s*\(/g,
    message: 'network calls belong behind the platform transport',
  },
  {
    rule: 'no-event-source',
    pattern: /new\s+EventSource\b/g,
    message: 'SSE belongs to the platform event plane; the webview cannot send an auth header',
  },
  {
    rule: 'no-web-storage',
    pattern: /\b(?:localStorage|sessionStorage|document\.cookie)\b/g,
    message: 'no credential and no domain row goes in web storage',
  },
  {
    rule: 'no-tauri-import',
    pattern: /from\s+['"]@tauri-apps\//g,
    message: 'import the platform interface from src/platform, not the runtime',
  },
  {
    rule: 'contract-no-any',
    pattern: /(?::\s*any\b|\bas any\b|\bz\.any\s*\(|<any>)/g,
    message: 'the contract layer models the wire as unknown + a schema, never as any',
    only: /platform\/contract\//,
  },
]

const SOURCE_EXTENSIONS = new Set(['.ts', '.tsx'])

/** The one directory allowed to reach the runtime, by path — not by exception comment. */
const ADAPTER_PATH = /(^|\/)platform\/tauri\//

export function findViolations({ path, code }) {
  if (ADAPTER_PATH.test(path)) return []

  const found = []

  stripComments(code)
    .split('\n')
    .forEach((line, index) => {
      for (const check of CHECKS) {
        if (check.only && !check.only.test(path)) continue
        check.pattern.lastIndex = 0
        if (check.pattern.test(line)) {
          found.push({ rule: check.rule, path, line: index + 1, message: check.message })
        }
      }
    })

  return found.sort((a, b) => RULES.indexOf(a.rule) - RULES.indexOf(b.rule) || a.line - b.line)
}

export function scanTree({ root }) {
  const files = sourceFiles(root)

  if (files.length === 0) throw new Error(`no files to scan under ${root}`)

  return files
    .flatMap((file) =>
      findViolations({ path: toPosix(relative(root, file)), code: readFileSync(file, 'utf8') }),
    )
    .sort((a, b) => RULES.indexOf(a.rule) - RULES.indexOf(b.rule) || a.line - b.line)
}

function sourceFiles(dir) {
  let entries
  try {
    entries = readdirSync(dir, { recursive: true, encoding: 'utf8' })
  } catch {
    return []
  }

  return entries
    .map((entry) => (typeof entry === 'string' ? join(dir, entry) : join(dir, entry.toString())))
    .filter((full) => {
      const name = full.split(/[\\/]/).pop() ?? ''
      if (name.endsWith('.test.ts') || name.endsWith('.test.tsx')) return false
      if (!SOURCE_EXTENSIONS.has(extensionOf(name))) return false
      try {
        return statSync(full).isFile()
      } catch {
        return false
      }
    })
}

function extensionOf(name) {
  const dot = name.lastIndexOf('.')
  return dot === -1 ? '' : name.slice(dot)
}

/** Reported paths are POSIX so a Windows CI run prints the same text as a local one. */
function toPosix(path) {
  return path.split(win32.sep).join(posix.sep)
}

/**
 * Comments are where a banned call survives a naive grep — a doc line that says
 * "never call fetch()" is not a call. Line structure is preserved so the reported
 * line numbers still point at the source.
 */
function stripComments(code) {
  let out = ''
  let index = 0
  let mode = 'code'
  let quote = ''

  while (index < code.length) {
    const char = code[index]
    const next = code[index + 1]

    if (mode === 'code') {
      if (char === '/' && next === '/') {
        mode = 'line'
        out += '  '
        index += 2
        continue
      }
      if (char === '/' && next === '*') {
        mode = 'block'
        out += '  '
        index += 2
        continue
      }
      if (char === '"' || char === "'" || char === '`') {
        quote = char
        mode = 'string'
      }
      out += char
      index += 1
      continue
    }

    if (mode === 'line') {
      if (char === '\n') {
        mode = 'code'
        out += '\n'
      } else out += ' '
      index += 1
      continue
    }

    if (mode === 'block') {
      if (char === '*' && next === '/') {
        mode = 'code'
        out += '  '
        index += 2
        continue
      }
      out += char === '\n' ? '\n' : ' '
      index += 1
      continue
    }

    // string: keep it verbatim, honour escapes, end on the matching quote
    if (char === '\\') {
      out += char + (next ?? '')
      index += 2
      continue
    }
    if (char === quote) {
      mode = 'code'
      quote = ''
    }
    out += char
    index += 1
  }

  return out
}

const isMain = process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  const here = dirname(fileURLToPath(import.meta.url))
  const srcRoot = resolve(here, '..', 'src')
  const violations = scanTree({ root: srcRoot })

  if (violations.length > 0) {
    for (const violation of violations) {
      console.error(`${violation.path}:${violation.line}  ${violation.rule}  ${violation.message}`)
    }
    console.error(`platform boundary: ${violations.length} violation(s)`)
    process.exitCode = 1
  } else {
    console.log(`platform boundary: OK (${sourceFiles(srcRoot).length} files outside the adapters)`)
  }
}

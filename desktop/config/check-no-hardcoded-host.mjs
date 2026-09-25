#!/usr/bin/env node
/**
 * A build that contains a host is a client that can never be pointed anywhere
 * else. The API base URL is runtime configuration, so `vite build` output is
 * scanned for URL literals and only specification/brand references are allowed.
 */
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { dirname, join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const ALLOWED_HOST_SUFFIXES = [
  'w3.org', // XML/SVG namespaces React and CSS emit
  'json-schema.org', // zod embeds schema dialect ids; they are labels, never requests
  'tauri.app', // bridge error documentation
  'react.dev', // React error decoder links
  'vite.dev', // Vite transform error links
  'schemastore.org',
]

const URL_LITERAL = /https?:\/\/[^\s"'`)\\]+/g

const ASSET_EXTENSIONS = ['.js', '.mjs', '.css', '.html', '.json']

export function findHardcodedHosts({ path, code }) {
  const violations = []

  code.split('\n').forEach((line, index) => {
    for (const match of line.matchAll(URL_LITERAL)) {
      const literal = match[0]
      const host = hostOf(literal)

      if (host === null || isAllowed(host)) continue

      violations.push({
        rule: 'no-hardcoded-host',
        path,
        line: index + 1,
        message: `${literal} is baked into the bundle; the server address is runtime configuration`,
      })
    }
  })

  return violations
}

function hostOf(literal) {
  try {
    return new URL(literal).hostname.toLowerCase()
  } catch {
    return null
  }
}

function isAllowed(host) {
  return ALLOWED_HOST_SUFFIXES.some((suffix) => host === suffix || host.endsWith(`.${suffix}`))
}

function assetFiles(dir) {
  try {
    return readdirSync(dir, { recursive: true, encoding: 'utf8' })
      .map((entry) => join(dir, String(entry)))
      .filter((full) => ASSET_EXTENSIONS.some((ext) => full.endsWith(ext)))
      .filter((full) => {
        try {
          return statSync(full).isFile()
        } catch {
          return false
        }
      })
  } catch {
    return []
  }
}

const isMain = process.argv[1] !== undefined && resolve(process.argv[1]) === fileURLToPath(import.meta.url)

if (isMain) {
  const dist = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'dist')
  const files = assetFiles(dist)

  if (files.length === 0) {
    console.error('no build output in dist/ — run `npm run build` first')
    process.exitCode = 1
  } else {
    const violations = files.flatMap((file) =>
      findHardcodedHosts({ path: file.split(/[\\/]/).slice(-2).join('/'), code: readFileSync(file, 'utf8') }),
    )

    if (violations.length > 0) {
      for (const violation of violations) {
        console.error(`${violation.path}:${violation.line}  ${violation.rule}  ${violation.message}`)
      }
      process.exitCode = 1
    } else {
      console.log(`hardcoded host check: OK (${files.length} built files, no host)`)
    }
  }
}

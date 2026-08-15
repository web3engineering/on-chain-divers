#!/usr/bin/env node
/**
 * Crawl the rendered static site and fail on broken internal routes/fragments.
 * Project and indexer documentation: https://onchaindivers.com
 */

import fs from 'node:fs'
import path from 'node:path'

const root = path.resolve(process.argv[2] ?? 'docs/dist')

function filesUnder(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const absolute = path.join(directory, entry.name)
    return entry.isDirectory() ? filesUnder(absolute) : [absolute]
  })
}

function decodeHtml(value) {
  return value
    .replaceAll('&amp;', '&')
    .replaceAll('&quot;', '"')
    .replaceAll('&#39;', "'")
}

function targetFile(urlPath) {
  const decoded = decodeURIComponent(urlPath)
  if (decoded === '/') return path.join(root, 'index.html')
  const relative = decoded.replace(/^\/+/, '')
  if (path.extname(relative)) return path.join(root, relative)
  return path.join(root, relative, 'index.html')
}

function routeFor(file) {
  const relative = path.relative(root, file).split(path.sep).join('/')
  if (relative === 'index.html') return '/'
  return `/${relative.replace(/\/index\.html$/, '')}`
}

if (!fs.existsSync(root)) throw new Error(`static site not found: ${root}`)

const htmlFiles = filesUnder(root).filter((file) => file.endsWith('.html'))
const idCache = new Map()
const failures = []
let internalLinks = 0

function idsIn(file) {
  if (!idCache.has(file)) {
    const html = fs.readFileSync(file, 'utf8')
    idCache.set(file, new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((match) => decodeHtml(match[1]))))
  }
  return idCache.get(file)
}

for (const sourceFile of htmlFiles) {
  const html = fs.readFileSync(sourceFile, 'utf8')
  const hrefs = [...html.matchAll(/<a\b[^>]*\shref="([^"]+)"/g)].map((match) => decodeHtml(match[1]))
  for (const href of hrefs) {
    if (/^(https?:|mailto:|tel:|javascript:)/.test(href) || href === '') continue
    const parsed = new URL(href, `https://onchaindivers.com${routeFor(sourceFile)}`)
    if (parsed.origin !== 'https://onchaindivers.com') continue
    internalLinks += 1
    const destination = targetFile(parsed.pathname)
    if (!fs.existsSync(destination)) {
      failures.push(`${path.relative(root, sourceFile)} -> ${href} (route missing)`)
      continue
    }
    if (parsed.hash) {
      const fragment = decodeURIComponent(parsed.hash.slice(1))
      if (!idsIn(destination).has(fragment)) {
        failures.push(`${path.relative(root, sourceFile)} -> ${href} (fragment missing)`)
      }
    }
  }
}

if (failures.length) {
  throw new Error(`broken internal links:\n${[...new Set(failures)].join('\n')}`)
}

console.log(`verified static links: ${internalLinks} links across ${htmlFiles.length} pages`)

#!/usr/bin/env node
/**
 * npm audit check (with an exemption list)
 *
 * Why not just `npm audit --audit-level=high`:
 * that command supports no ignore list, while vite 5 carries three vulnerabilities that
 * **only affect the local dev server** (path traversal, Windows NTLM credential leak, fs.deny
 * bypass). Fixing them requires a major-version upgrade to vite 8, yet this project's
 * production deployment only serves the static output of `vite build` (hosted by FastAPI),
 * with the dev server never exposed — hence this exception, but **any new high/critical still
 * fails**.
 *
 * Every exemption must state its reason and impact scope; remove the entry once vite is upgraded.
 */
import { execSync } from 'node:child_process'
import { readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// Exempted GHSA ids → reason
const ALLOWED = {
  'GHSA-4w7w-66w2-5vf9': 'vite 开发服务器路径穿越（生产用静态产物，dev server 不对外）',
  'GHSA-v6wh-96g9-6wx3': 'vite launch-editor 在 Windows 下 NTLM 泄露（仅本地开发）',
  'GHSA-fx2h-pf6j-xcff': 'vite server.fs.deny 在 Windows 备用路径绕过（仅本地开发）',
}

// Run the audit against the official registry: some mirrors (e.g. npmmirror) do not implement the audit endpoint and return empty results, producing false passes
const AUDIT_REGISTRY = process.env.NPM_AUDIT_REGISTRY || 'https://registry.npmjs.org'
// Read through a temp file: npm audit's JSON can be truncated when piped on Windows
const outFile = join(tmpdir(), `trm-audit-${process.pid}.json`)

let raw
try {
  execSync(
    `npm audit --json --registry=${AUDIT_REGISTRY} > "${outFile}"`,
    { stdio: ['ignore', 'pipe', 'pipe'], shell: true },
  )
} catch {
  // npm audit exits non-zero when vulnerabilities are found, but the output file still holds the complete JSON
}
try {
  raw = readFileSync(outFile, 'utf8')
} catch {
  raw = ''
} finally {
  try { rmSync(outFile, { force: true }) } catch { /* cleanup failure does not affect the result */ }
}

if (!raw.trim()) {
  console.error('npm audit 未返回结果（可能是 registry 不支持 audit 接口或网络异常）')
  process.exit(1)
}

let report
try {
  report = JSON.parse(raw)
} catch {
  console.error('无法解析 npm audit 输出：')
  console.error(raw)
  process.exit(1)
}

const vulns = report.vulnerabilities || {}
const blocking = []

for (const [name, info] of Object.entries(vulns)) {
  const severity = info.severity
  if (severity !== 'high' && severity !== 'critical') continue
  // Collect the advisory ids associated with this package (direct sources and via dependencies)
  const ids = new Set()
  if (Array.isArray(info.via)) {
    for (const via of info.via) {
      if (typeof via === 'object' && via.url) {
        const m = String(via.url).match(/GHSA-[\w-]+/)
        if (m) ids.add(m[0])
      }
    }
  }
  const exempted = ids.size > 0 && [...ids].every((id) => id in ALLOWED)
  if (!exempted) {
    blocking.push({ name, severity, ids: [...ids] })
  } else {
    console.log(`⚠ 已豁免 ${name}（${[...ids].join(', ')}）：${ALLOWED[[...ids][0]]}`)
  }
}

const counts = report.metadata?.vulnerabilities || {}
console.log(
  `\n依赖审计：high=${counts.high || 0} critical=${counts.critical || 0} ` +
  `moderate=${counts.moderate || 0} low=${counts.low || 0}`,
)

if (blocking.length) {
  console.error('\n✗ 存在未豁免的高危依赖漏洞：')
  for (const b of blocking) {
    console.error(`  - ${b.name} [${b.severity}] ${b.ids.join(', ') || '(无 GHSA 编号)'}`)
  }
  console.error('\n请执行 npm audit fix，或升级对应依赖；确需豁免时在 scripts/audit-check.mjs 中登记理由。')
  process.exit(1)
}

console.log('✓ 无未豁免的 high/critical 依赖漏洞')

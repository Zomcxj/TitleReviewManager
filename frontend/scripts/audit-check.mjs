#!/usr/bin/env node
/**
 * npm audit 检查（带豁免清单）
 *
 * 为什么不用 `npm audit --audit-level=high`：
 * 该命令不支持忽略清单，而 vite 5 存在三条**仅影响本地开发服务器**的漏洞
 * （路径穿越、Windows NTLM 泄露、fs.deny 绕过），修复需跨大版本升级到 vite 8，
 * 而本项目生产部署只使用 `vite build` 的静态产物（由 FastAPI 托管），
 * 开发服务器不对外暴露 —— 因此按例外处理，但**新增的 high/critical 仍会失败**。
 *
 * 豁免项需写明理由与影响面；升级 vite 后应删除对应条目。
 */
import { execSync } from 'node:child_process'
import { readFileSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

// 豁免的 GHSA 编号 → 理由
const ALLOWED = {
  'GHSA-4w7w-66w2-5vf9': 'vite 开发服务器路径穿越（生产用静态产物，dev server 不对外）',
  'GHSA-v6wh-96g9-6wx3': 'vite launch-editor 在 Windows 下 NTLM 泄露（仅本地开发）',
  'GHSA-fx2h-pf6j-xcff': 'vite server.fs.deny 在 Windows 备用路径绕过（仅本地开发）',
}

// 审计走官方 registry：部分镜像（如 npmmirror）未实现 audit 接口，会返回空结果造成假通过
const AUDIT_REGISTRY = process.env.NPM_AUDIT_REGISTRY || 'https://registry.npmjs.org'
// 经临时文件读取：npm audit 的 JSON 在 Windows 下经管道可能被截断
const outFile = join(tmpdir(), `trm-audit-${process.pid}.json`)

let raw
try {
  execSync(
    `npm audit --json --registry=${AUDIT_REGISTRY} > "${outFile}"`,
    { stdio: ['ignore', 'pipe', 'pipe'], shell: true },
  )
} catch {
  // npm audit 有漏洞时退出码非 0，但输出文件仍含完整 JSON
}
try {
  raw = readFileSync(outFile, 'utf8')
} catch {
  raw = ''
} finally {
  try { rmSync(outFile, { force: true }) } catch { /* 清理失败不影响结果 */ }
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
  // 收集该包关联的 advisory id（直接来源与经由依赖）
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

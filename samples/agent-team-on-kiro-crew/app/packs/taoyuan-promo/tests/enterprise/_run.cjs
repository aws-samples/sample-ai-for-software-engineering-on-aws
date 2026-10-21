// 跑 tests/ 下的全部检查，认的文件和 kirocrew-team 测试墙一样。Node 18 到 24 都能用
// （Node 22 起 `node --test tests/` 不再接受目录）。
//
//   node tests/enterprise/_run.cjs            全部
//   node tests/enterprise/_run.cjs android    只跑路径里带 android 的
'use strict'
const fs = require('node:fs')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const TESTS = path.resolve(__dirname, '..')
const ROOT = path.dirname(TESTS)
const TEST_FILE = /(\.test|[-_]test)\.[cm]?js$|^test([-_].*)?\.[cm]?js$/

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((ent) => {
    const p = path.join(dir, ent.name)
    if (ent.isDirectory()) return ent.name.startsWith('.') || ent.name === 'node_modules' ? [] : files(p)
    return ent.isFile() && TEST_FILE.test(ent.name) ? [p] : []
  })
}

const only = process.argv.slice(2)
const list = files(TESTS)
  .map((f) => path.relative(ROOT, f))
  .filter((f) => !only.length || only.some((s) => f.includes(s)))
  .sort()
if (!list.length) {
  console.error('没有找到检查文件')
  process.exit(1)
}
// 每个用例最多 30 秒；跑完就退出，不等没关掉的服务或定时器（Node 22 起支持）
const [major] = process.versions.node.split('.').map(Number)
const extra = major >= 22 ? ['--test-force-exit', '--test-timeout=30000'] : []
const r = spawnSync(process.execPath, ['--test', '--test-reporter=spec', ...extra, ...list], { cwd: ROOT, stdio: 'inherit' })
process.exit(r.status === null ? 1 : r.status)

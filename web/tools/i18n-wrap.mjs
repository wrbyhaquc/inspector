// Wrap the Chinese texts of .ts/.tsx files in t() (src/i18n): node tools/i18n-wrap.mjs <file> [...] [--dry]
//
// What it changes (the TypeScript parser reads the file, so code structure is never guessed):
//   '新增規則'                    -> t('新增規則')
//   `第 ${n} 步`                  -> t('第 {n} 步', { n })              (other expressions: { p1: expr })
//   <span>共 {n} 條</span>        -> <span>{t('共 {n} 條', { n })}</span>   (a run of text and simple values: one text)
//   placeholder="說明"            -> placeholder={t('說明')}
// What it leaves (data, not words to show) and lists for a look: object keys, types, imports, `case '...':`,
// comparisons (=== '工作中'), .includes('...') / .startsWith('...') ..., x['...'], and the attributes key, value, id,
// name, to, href, src, type, className, style, htmlFor, role.
import fs from 'node:fs'
import path from 'node:path'
import ts from 'typescript'

const CJK = /[㐀-鿿]/
const ATTR_SKIP = new Set(['key', 'className', 'value', 'id', 'name', 'to', 'href', 'src', 'type', 'style', 'htmlFor', 'role'])
const CMP = new Set([ts.SyntaxKind.EqualsEqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsEqualsToken, ts.SyntaxKind.EqualsEqualsToken, ts.SyntaxKind.ExclamationEqualsToken])
const DATA_CALLS = new Set(['startsWith', 'endsWith', 'includes', 'indexOf', 'split', 'replace', 'replaceAll', 'match', 'test', 'search', 'localeCompare', 'getItem', 'setItem'])
const I18N = path.resolve('src/i18n')
const dry = process.argv.includes('--dry')

const quote = s => `'${s.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/\n/g, '\\n')}'`

function jsxText(raw) {
  // what JSX shows for a piece of text: lines trimmed and joined by a space when it spans lines
  if (!raw.includes('\n')) return raw
  return raw.split('\n').map((l, i, a) => (i === 0 ? l.replace(/\s+$/, '') : i === a.length - 1 ? l.replace(/^\s+/, '') : l.trim()))
    .filter(l => l.length).join(' ')
}

function paramName(expr, used, i) {
  let n = ts.isIdentifier(expr) ? expr.text : ts.isPropertyAccessExpression(expr) ? expr.name.text : `p${i}`
  if (!/^\w+$/.test(n)) n = `p${i}`
  let k = n, j = 2
  while (used.has(k)) k = `${n}${j++}`
  used.add(k)
  return k
}

function hasCjkString(node) {
  let found = false
  const walk = n => {
    if (found) return
    if ((ts.isStringLiteral(n) || ts.isNoSubstitutionTemplateLiteral(n) || ts.isJsxText(n)) && CJK.test(n.text)) found = true
    else if (ts.isTemplateExpression(n) && (CJK.test(n.head.text) || n.templateSpans.some(s => CJK.test(s.literal.text)))) found = true
    else ts.forEachChild(n, walk)
  }
  walk(node)
  return found
}
const hasJsx = node => {
  let found = false
  const walk = n => { if (found) return; if (ts.isJsxElement(n) || ts.isJsxSelfClosingElement(n) || ts.isJsxFragment(n)) found = true; else ts.forEachChild(n, walk) }
  walk(node)
  return found
}

function call(sf, msg, params) {
  if (!params.length) return `t(${quote(msg)})`
  const items = params.map(([k, e]) => (e === k ? k : `${k}: ${e}`)).join(', ')
  return `t(${quote(msg)}, { ${items} })`
}

function dataUse(node) {
  // a string that is data, not a text to show
  const p = node.parent
  if (!p) return 'no parent'
  if (ts.isPropertyAssignment(p) && p.name === node) return null           // a key: left as it is, not reported
  if (ts.isCaseClause(p)) return 'case'
  if (ts.isBinaryExpression(p) && CMP.has(p.operatorToken.kind)) return 'comparison'
  if (ts.isElementAccessExpression(p) && p.argumentExpression === node) return 'x[...]'
  if (ts.isCallExpression(p) && ts.isPropertyAccessExpression(p.expression) && DATA_CALLS.has(p.expression.name.text)) return `.${p.expression.name.text}()`
  if (ts.isLiteralTypeNode(p) || ts.isImportDeclaration(p) || ts.isExportDeclaration(p)) return null
  if (ts.isJsxAttribute(p) && ATTR_SKIP.has(p.name.getText())) return `${p.name.getText()}=`
  return undefined
}

/** a local variable / parameter named t would hide the imported t(): rename it (scope-aware) to tx */
function renameLocalT(file, src) {
  const kind = file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
  const sf0 = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, kind)
  const decls = []
  const walk = n => {
    if ((ts.isVariableDeclaration(n) || ts.isParameter(n) || ts.isBindingElement(n)) && n.name && ts.isIdentifier(n.name) && n.name.text === 't') decls.push(n.name.getStart(sf0))
    ts.forEachChild(n, walk)
  }
  walk(sf0)
  if (!decls.length) return src
  const host = {
    getScriptFileNames: () => [file], getScriptVersion: () => '1', getScriptSnapshot: f => (f === file ? ts.ScriptSnapshot.fromString(src) : undefined),
    getCurrentDirectory: () => process.cwd(), getCompilationSettings: () => ({ jsx: ts.JsxEmit.ReactJSX, allowJs: true, noResolve: true }),
    getDefaultLibFileName: o => ts.getDefaultLibFilePath(o), fileExists: f => f === file, readFile: f => (f === file ? src : undefined),
  }
  const ls = ts.createLanguageService(host)
  const spots = new Set()
  for (const pos of decls) for (const l of ls.findRenameLocations(file, pos, false, false) ?? []) spots.add(l.textSpan.start)
  let out = src
  for (const p of [...spots].sort((a, b) => b - a)) out = out.slice(0, p) + 'tx' + out.slice(p + 1)
  return out
}

function run(file) {
  const src = renameLocalT(file, fs.readFileSync(file, 'utf8'))
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const edits = [], left = []
  const add = (start, end, text) => edits.push({ start, end, text })
  const where = n => `${path.relative('.', file)}:${sf.getLineAndCharacterOfPosition(n.getStart(sf)).line + 1}`

  function children(node) {
    // runs of JSX text and simple values inside one element: one text each
    const kids = node.children
    let i = 0
    while (i < kids.length) {
      const k = kids[i]
      const textish = c => ts.isJsxText(c) || (ts.isJsxExpression(c) && c.expression && !hasJsx(c.expression) && !hasCjkString(c.expression))
      if (!textish(k)) {
        const nearText = c => c && ts.isJsxText(c) && CJK.test(c.text)
        if (ts.isJsxExpression(k) && k.expression && hasCjkString(k.expression) && (nearText(kids[i - 1]) || nearText(kids[i + 1])))
          left.push(`${where(k)} 句子被含中文的值拆開,請手動寫成一整句`)
        visit(k); i++; continue
      }
      let j = i
      while (j < kids.length && textish(kids[j])) j++
      const runKids = kids.slice(i, j)
      const withText = runKids.some(c => ts.isJsxText(c) && CJK.test(c.text))
      if (!withText || runKids.some(c => ts.isJsxText(c) && /[&{}]/.test(c.text))) {
        if (withText) left.push(`${where(runKids[0])} JSX 文字含 & 或括號,請手動處理`)
        runKids.forEach(c => { if (!ts.isJsxText(c)) visit(c) })
        i = j; continue
      }
      // the run without its outer whitespace
      const first = runKids[0], last = runKids[runKids.length - 1]
      let start = first.getStart(sf), end = last.end
      let lead = '', trail = ''
      if (ts.isJsxText(first)) { const m = first.text.match(/^\s*/)[0]; lead = m; start = first.pos + m.length }
      if (ts.isJsxText(last)) { const m = last.text.match(/\s*$/)[0]; trail = m; end = last.end - m.length }
      const used = new Set(), params = []
      let msg = ''
      runKids.forEach((c, n) => {
        if (ts.isJsxText(c)) {
          let s = c.text
          if (c === first) s = s.replace(/^\s+/, '')
          if (c === last) s = s.replace(/\s+$/, '')
          msg += jsxText(s)
        } else {
          const e = c.expression
          const k = paramName(e, used, params.length + 1)
          params.push([k, e.getText(sf)])
          msg += `{${k}}`
        }
      })
      if (msg.trim()) add(start, end, `{${call(sf, msg, params)}}`)
      void lead; void trail
      i = j
    }
  }

  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node) || ts.isTypeNode(node) && !ts.isTypeLiteralNode(node)) return
    if (ts.isCallExpression(node)) {
      const c = node.expression
      if (ts.isIdentifier(c) && c.text === 't') return
      if (ts.isPropertyAccessExpression(c) && ts.isIdentifier(c.expression) && c.expression.text === 'console') return
    }
    if (ts.isTaggedTemplateExpression(node)) return
    if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
      if (ts.isJsxElement(node)) visit(node.openingElement)
      children(node)
      return
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && CJK.test(node.text)) {
      const why = dataUse(node)
      if (why === null) return
      if (why) { left.push(`${where(node)} ${why} ${JSON.stringify(node.text).slice(0, 40)}`); return }
      const inAttr = node.parent && ts.isJsxAttribute(node.parent)
      add(node.getStart(sf), node.end, inAttr ? `{${call(sf, node.text, [])}}` : call(sf, node.text, []))
      return
    }
    if (ts.isTemplateExpression(node) && (CJK.test(node.head.text) || node.templateSpans.some(s => CJK.test(s.literal.text)))) {
      const why = dataUse(node)
      if (why) { left.push(`${where(node)} ${why} (樣板字串)`); return }
      if (node.templateSpans.some(s => hasCjkString(s.expression) || hasJsx(s.expression))) {
        left.push(`${where(node)} 樣板字串的值裡還有中文,請手動處理`); ts.forEachChild(node, visit); return
      }
      const used = new Set(), params = []
      let msg = node.head.text
      node.templateSpans.forEach((s, n) => {
        const k = paramName(s.expression, used, n + 1)
        params.push([k, s.expression.getText(sf)])
        msg += `{${k}}${s.literal.text}`
      })
      add(node.getStart(sf), node.end, call(sf, msg, params))
      return
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  if (!edits.length) return { file, n: 0, left }
  edits.sort((a, b) => b.start - a.start)
  let out = src
  for (const e of edits) out = out.slice(0, e.start) + e.text + out.slice(e.end)
  // import { t }
  let rel = path.relative(path.dirname(path.resolve(file)), I18N).replace(/\\/g, '/')
  if (!rel.startsWith('.')) rel = './' + rel
  if (!new RegExp(`import \\{[^}]*\\bt\\b[^}]*\\} from '${rel}'`).test(out)) {
    const imp = new RegExp(`import \\{([^}]*)\\} from '${rel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}'`)
    if (imp.test(out)) out = out.replace(imp, (m, names) => `import {${names.replace(/\s*$/, '')}, t } from '${rel}'`)
    else {
      const lastImport = [...out.matchAll(/^import [^\n]*\n(?:[^\n]*\n)*?.*?from '[^']+'\n/gm)].pop()
      const at = lastImport ? lastImport.index + lastImport[0].length : 0
      out = out.slice(0, at) + `import { t } from '${rel}'\n` + out.slice(at)
    }
  }
  if (!dry) fs.writeFileSync(file, out)
  return { file, n: edits.length, left }
}

const files = process.argv.slice(2).filter(a => !a.startsWith('--'))
let total = 0
for (const f of files) {
  const r = run(f)
  total += r.n
  console.log(`${r.file}: 包進 t() ${r.n} 處${r.left.length ? `,留下 ${r.left.length} 處(資料或要手動)` : ''}`)
  for (const l of r.left) console.log(`   ${l}`)
}
console.log(`合計 ${total} 處${dry ? '(試跑,沒有寫入)' : ''}`)

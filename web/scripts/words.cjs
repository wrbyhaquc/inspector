// One-off source rewrite: the device word comes from the project (lib/project.ts words.device) instead of a fixed word.
// Rewrites string literals, template literals and JSX text that contain WORD; comments are left alone.
// usage: node scripts/words.cjs <WORD> <key> <file...>
const fs = require('fs')
const path = require('path')
const ts = require('typescript')

const [word, key, ...files] = process.argv.slice(2)
const expr = `words.${key}`
let total = 0
for (const file of files) {
  const src = fs.readFileSync(file, 'utf8')
  const sf = ts.createSourceFile(file, src, ts.ScriptTarget.Latest, true, file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS)
  const edits = []                                    // [start, end, text]
  const esc = s => s.replace(/\\/g, '\\\\').replace(/`/g, '\\`').replace(/\$\{/g, '\\${')
  const visit = node => {
    if (ts.isStringLiteral(node) && node.text.includes(word)) {
      const tpl = '`' + node.text.split(word).map(esc).join('${' + expr + '}') + '`'
      const inAttr = node.parent && ts.isJsxAttribute(node.parent)
      edits.push([node.getStart(sf), node.getEnd(), inAttr ? `{${tpl}}` : tpl])
      return
    }
    if ((ts.isNoSubstitutionTemplateLiteral(node) || ts.isTemplateHead(node) || ts.isTemplateMiddle(node) || ts.isTemplateTail(node))) {
      const raw = src.slice(node.getStart(sf), node.getEnd())
      if (raw.includes(word)) edits.push([node.getStart(sf), node.getEnd(), raw.split(word).join('${' + expr + '}')])
    }
    if (ts.isJsxText(node) && node.text.includes(word)) {
      const raw = src.slice(node.pos, node.end)
      edits.push([node.pos, node.end, raw.split(word).join(`{${expr}}`)])
      return
    }
    ts.forEachChild(node, visit)
  }
  visit(sf)
  if (!edits.length) continue
  let out = src
  for (const [a, b, t] of edits.sort((x, y) => y[0] - x[0])) out = out.slice(0, a) + t + out.slice(b)
  if (!/import \{[^}]*\bwords\b[^}]*\} from '[^']*lib\/project'/.test(out)) {
    const rel = path.relative(path.dirname(file), path.join(__dirname, '..', 'src', 'lib', 'project')).replace(/\\/g, '/')
    const spec = rel.startsWith('.') ? rel : './' + rel
    const m = out.match(/import \{([^}]*)\} from '([^']*lib\/project)'/)
    if (m) out = out.replace(m[0], `import {${m[1].replace(/\s*$/, '')}, words } from '${m[2]}'`)
    else {
      const lastImport = [...out.matchAll(/^import .*$/gm)].pop()
      const at = lastImport ? lastImport.index + lastImport[0].length : 0
      out = out.slice(0, at) + `\nimport { words } from '${spec}'` + out.slice(at)
    }
  }
  fs.writeFileSync(file, out)
  total += edits.length
  console.log(`${file}: ${edits.length}`)
}
console.log('total', total)

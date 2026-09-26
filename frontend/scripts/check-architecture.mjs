import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import ts from 'typescript'
import { parse as parseVue } from '@vue/compiler-sfc'

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const fixtureMode = process.argv.includes('--fixtures')
const root = path.resolve(scriptDir, fixtureMode ? 'architecture-fixtures' : '../src')
const layers = ['shared', 'modules', 'pages', 'app']
// These old consumers are migrated by P2–P6; P7 removes the transition entirely.
const legacy = new Set([
  'api',
  'components',
  'composables',
  'domain',
  'adapters',
  'router',
  'views',
  'types',
  'main.ts',
  'App.vue',
  'assets',
])
// Only the router may load old route entries while their owner packages migrate.
const legacyRoute = (from, to) => from === 'app/router.ts' && to.startsWith('views/')
const relative = (file) => path.relative(root, file).split(path.sep).join('/')
const owner = (file) => relative(file).split('/')[0]
const moduleName = (file) => (owner(file) === 'modules' ? relative(file).split('/')[1] : undefined)
const isModel = (file) => relative(file).includes('/model/')
const isPublic = (file) => path.basename(file) === 'public.ts'
const externalEffect =
  /^(?:vue(?:-router)?|@vue\/|axios(?:\/|$)|element-plus(?:\/|$)|lucide-vue-next(?:\/|$)|node:|https?$)/
const forbiddenGlobals = new Set([
  'window',
  'document',
  'localStorage',
  'sessionStorage',
  'fetch',
  'XMLHttpRequest',
  'EventSource',
  'WebSocket',
  'navigator',
])

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name)
    return entry.isDirectory() ? files(file) : /\.(ts|vue)$/.test(entry.name) ? [file] : []
  })
}
function resolveImport(file, specifier) {
  if (!specifier.startsWith('@/') && !specifier.startsWith('.')) return undefined
  const base = specifier.startsWith('@/')
    ? path.join(root, specifier.slice(2))
    : path.resolve(path.dirname(file), specifier)
  return [base, `${base}.ts`, `${base}.vue`, `${base}.js`, path.join(base, 'index.ts')].find(
    (candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile(),
  )
}
function parse(file) {
  const raw = fs.readFileSync(file, 'utf8')
  const descriptor = file.endsWith('.vue') ? parseVue(raw, { filename: file }) : undefined
  if (descriptor?.errors.length)
    throw new Error(`${relative(file)}: ${descriptor.errors.join(', ')}`)
  const code = descriptor
    ? [descriptor.descriptor.script, descriptor.descriptor.scriptSetup]
        .filter(Boolean)
        .map((script) => script.content)
        .join('\n')
    : raw
  const tree = ts.createSourceFile(file, code, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS)
  if (tree.parseDiagnostics.length) throw new Error(`${relative(file)}: invalid TypeScript`)
  const imports = []
  const effects = new Set()
  function add(node) {
    if (node && ts.isStringLiteralLike(node)) imports.push(node.text)
    else if (node) effects.add('nonliteral-import')
  }
  function visit(node) {
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) add(node.moduleSpecifier)
    if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference))
      add(node.moduleReference.expression)
    if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument)) add(node.argument.literal)
    if (
      ts.isCallExpression(node) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        (ts.isIdentifier(node.expression) && node.expression.text === 'require'))
    )
      add(node.arguments[0])
    if (ts.isIdentifier(node) && forbiddenGlobals.has(node.text)) {
      // Property names do not imply access to a browser global (e.g. DTO.window).
      if (!(ts.isPropertySignature(node.parent) && node.parent.name === node))
        effects.add(node.text)
    }
    ts.forEachChild(node, visit)
  }
  visit(tree)
  const mutable = tree.statements.some(
    (node) => ts.isVariableStatement(node) && !(node.declarationList.flags & ts.NodeFlags.Const),
  )
  return { imports, effects, mutable }
}

function check(sourceFiles) {
  const violations = []
  const graph = new Map()
  const add = (file, rule, detail) => violations.push({ file: relative(file), rule, detail })
  for (const file of sourceFiles) {
    const parsed = parse(file)
    const from = owner(file)
    const rel = relative(file)
    const old = legacy.has(from)
    const edges = []
    graph.set(file, edges)
    for (const specifier of parsed.imports) {
      const target = resolveImport(file, specifier)
      if (target) edges.push(target)
      if (old) continue
      if (specifier.startsWith('@/') || specifier.startsWith('.')) {
        if (!target) {
          add(file, 'unresolved', specifier)
          continue
        }
        const to = owner(target)
        if (legacy.has(to) && !legacyRoute(rel, relative(target)))
          add(file, 'legacy-import', specifier)
        if (layers.indexOf(from) < layers.indexOf(to)) add(file, 'layer-direction', specifier)
        if (to === 'modules') {
          if (moduleName(file) === moduleName(target)) {
            if (isPublic(target) && !isPublic(file)) add(file, 'own-public', specifier)
          } else {
            if (!isPublic(target) && !(from === 'app' && rel === 'app/bootstrap.ts' && relative(target).includes('/api/'))) add(file, 'module-public', specifier)
            if (
              from === 'modules' &&
              !(moduleName(file) === 'workflows' && moduleName(target) === 'resources')
            )
              add(file, 'module-direction', specifier)
          }
        }
        if (
          isModel(file) &&
          (['api', 'composables', 'ui', 'async'].some((part) =>
            relative(target).split('/').includes(part),
          ) ||
            target.endsWith('.vue'))
        )
          add(file, 'model-purity', specifier)
        if (
          file.endsWith('.vue') &&
          (relative(target).includes('/api/') || relative(target).startsWith('shared/api/'))
        )
          add(file, 'sfc-transport', specifier)
      } else {
        if (isModel(file) && externalEffect.test(specifier)) add(file, 'model-purity', specifier)
        if (/^axios(?:\/|$)/.test(specifier) && !rel.startsWith('shared/api/'))
          add(file, 'axios-owner', specifier)
        if (file.endsWith('.vue') && /^axios(?:\/|$)/.test(specifier))
          add(file, 'sfc-transport', specifier)
      }
    }
    for (const effect of parsed.effects) {
      if (effect === 'fetch') add(file, 'ordinary-http', effect)
      if (old) continue
      if (effect === 'nonliteral-import')
        add(file, 'nonliteral-import', 'cannot resolve statically')
      if (isModel(file) && forbiddenGlobals.has(effect)) add(file, 'model-purity', effect)
      if (
        file.endsWith('.vue') &&
        ['fetch', 'XMLHttpRequest', 'EventSource', 'WebSocket'].includes(effect)
      )
        add(file, 'sfc-transport', effect)
    }
    if (!old && isModel(file) && parsed.mutable) add(file, 'model-purity', 'mutable module state')
  }
  const active = new Set()
  const visited = new Set()
  function visit(file) {
    if (active.has(file)) {
      if (!legacy.has(owner(file))) add(file, 'cycle', 'dependency cycle')
      return
    }
    if (visited.has(file)) return
    active.add(file)
    for (const target of graph.get(file) ?? []) visit(target)
    active.delete(file)
    visited.add(file)
  }
  for (const file of sourceFiles) visit(file)
  return violations
}

const sourceFiles = files(root)
const violations = check(sourceFiles)
if (fixtureMode) {
  const expected = JSON.parse(fs.readFileSync(path.join(root, 'expected.json'), 'utf8'))
  const actual = Object.fromEntries(
    sourceFiles.map((file) => [
      relative(file),
      [
        ...new Set(
          violations.filter((entry) => entry.file === relative(file)).map((entry) => entry.rule),
        ),
      ].sort(),
    ]),
  )
  for (const [file, rules] of Object.entries(expected)) expected[file] = rules.sort()
  if (
    JSON.stringify(Object.entries(actual).sort()) !==
    JSON.stringify(Object.entries(expected).sort())
  ) {
    console.error(JSON.stringify({ expected, actual, violations }, null, 2))
    process.exit(1)
  }
  console.log(
    `architecture fixtures passed (${sourceFiles.length} files; real rules, positive and negative cases)`,
  )
} else if (violations.length) {
  console.error(
    violations.map(({ file, rule, detail }) => `${file}: ${rule}: ${detail}`).join('\n'),
  )
  process.exit(1)
} else
  console.log(
    `architecture check passed (${sourceFiles.length} files; legacy consumers expire P2–P7)`,
  )

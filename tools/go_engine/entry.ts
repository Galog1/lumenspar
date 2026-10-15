// Lumenspar's entry point into Genshin Optimizer's production formula engine
// ("WR": libs/gi/wr, libs/gi/sheets, libs/gi/uidata, what genshin-optimizer.com
// runs; MIT License, https://github.com/frzyc/genshin-optimizer).
// Bundled by tools/build_go_engine.py and run in Qt's QJSEngine. The sheets'
// UI is replaced by an inert stub whose JSX yields label objects:
// {ns, key, values} | {children} | string, passed through as-is.
//
//   LumensparGO.compute(json)      -> json   stats and every named formula, per member
//   LumensparGO.conditionals(json) -> json   the conditionals a team can toggle
//   LumensparGO.optimize(json)     -> json   best artifact builds for a target
//
// Shared request fields:
//   members: [{ char: { key, level, constellation, ascension, talent: { auto, skill, burst } },
//               weapon: { key, level, ascension, refinement },
//               artifacts?: [{ set, stats: [{ key, value }] }] }]   percent stats are fractions
//   conditional?: { [sheetKey]: { [condKey]: string } }   one map for the whole team
//   enemy?: { level?, res? }   res is a fraction (default level 100, res 0.1)
//   reactions?: string[]   per member: '' | 'vaporize' | 'melt' | 'spread' | 'aggravate'
//
// compute: + only?: number[] (default all), modes?: ('avg' | 'crit' | 'nonCrit')[] (default ['avg'])
//   -> { members: [null | { stats: { hp, atk, ..., <ele>_dmg_ },
//        formulas: [{ id, section, name, variant, subVariant, multi, <mode>: value }] }] }
//   Formula ids: `<talentKey>:<doc>:<field>`, `weapon:<doc>:<field>`, `reaction:<name>`.
//   Each mode is one full calculation, so callers ask only for what they show.
//
// conditionals: -> [{ src, sheet, name, label, teamBuff, kind, section, states: [{ value, label }] }]
//   (set `conditional[sheet][name] = value` to enable one)
//
// optimize: + target: { member, frames: [{ id, multiplier? }] },
//             minimums?: [{ key, value }]  final stats, fractions for %,
//             families: [[candidates x 5 slots]]  candidate = { id, <statKey>: value, <setKey>: 1 },
//             top?: number (default 5)
//   -> { builds: [{ ids, value }], evaluated, pruned }
//   The way GO's own optimizer works (TabOptimize + ComputeWorker): the target
//   member gets no artifacts, the artifact stats stay free ("dyn"), and every
//   family is pruned, precompiled and searched in full.
import { allArtifactSetKeys } from '@genshin-optimizer/gi/consts'
import {
  allArtifactData, getArtSheet, getCharSheet, getMoonsignSheet, getWeaponSheet,
  reactionData, resonanceData, resonanceSheets,
} from '@genshin-optimizer/gi/sheets'
import { uiDataForTeam } from '@genshin-optimizer/gi/uidata'
import {
  common, constant, dataObjForCharacterNew, dataObjForWeapon, dynamicData, infoManager,
  input, mergeData, optimize as wrOptimize, percent, precompute, prod, sum,
} from '@genshin-optimizer/gi/wr'
// The package index also pulls in the solver's workers; only this is needed.
import { pruneAll } from './libs/gi/solver/src/common'

type Member = { char: any; weapon: any; artifacts?: { set: string; stats: { key: string; value: number }[] }[] }
type Req = {
  members: Member[]
  conditional?: Record<string, Record<string, string>>
  enemy?: { level?: number; res?: number }
  reactions?: string[]
}

const STATS = ['hp', 'atk', 'def', 'eleMas', 'critRate_', 'critDMG_', 'enerRech_', 'heal_']
const ELES = ['pyro', 'hydro', 'electro', 'cryo', 'anemo', 'geo', 'dendro', 'physical']
const HIT_MODE: Record<string, string> = { avg: 'avgHit', crit: 'critHit', nonCrit: 'hit' }
const SLOTS = ['flower', 'plume', 'sands', 'goblet', 'circlet']
const artSets = new Set<string>(allArtifactSetKeys as readonly string[])

const num = (v: any): number | null => (typeof v === 'number' && isFinite(v) ? v : null)

function sheets(m: Member) {
  const key = m.char.key
  const charSheet: any = getCharSheet(key, 'F')
  const weaponSheet: any = getWeaponSheet(m.weapon.key)
  if (!charSheet || !weaponSheet) throw new Error(`no sheet for ${key}`)
  return { charSheet, weaponSheet }
}

// Like GO's getCharDataBundle (useCustom = false). `emptyArtsFor` leaves that
// member without artifacts: the optimizer's target.
function teamData(req: Req, hitMode: string, emptyArtsFor?: number): Record<string, any[]> {
  const res = (req.enemy?.res ?? 0.1) * 100
  const out: Record<string, any[]> = {}
  req.members.forEach((m, i) => {
    const { charSheet, weaponSheet } = sheets(m)
    const sheetData = mergeData([charSheet.data, weaponSheet.data, allArtifactData])
    const arts = i === emptyArtsFor ? [] : (m.artifacts ?? []).map((a) => ({
      art: Object.fromEntries(a.stats.map((s) => [s.key, s.key.endsWith('_') ? percent(s.value) : constant(s.value)])),
      artSet: { [a.set]: constant(1) },
    }))
    out[m.char.key] = [
      ...arts,
      dataObjForCharacterNew({
        key: m.char.key, level: m.char.level, constellation: m.char.constellation,
        ascension: m.char.ascension, talent: m.char.talent, infusionAura: '',
        customMultiTargets: [], conditional: req.conditional ?? {}, bonusStats: {},
        enemyOverride: {
          enemyLevel: req.enemy?.level ?? 100,
          ...Object.fromEntries(ELES.map((e) => [`${e}_enemyRes_`, res])),
        },
        hitMode, reaction: req.reactions?.[i] || undefined,
      } as any),
      dataObjForWeapon({ id: `w${i}`, ...m.weapon } as any),
      sheetData, common, resonanceData, reactionData,
    ]
  })
  return out
}

function calcFor(req: Req, hitMode: string, idx: number): any {
  const key = req.members[idx].char.key
  return (uiDataForTeam(teamData(req, hitMode) as any, 'F', key) as any)[key]!.target
}

// Documents (with their index) a calc can show.
function shown(docs: any[] | undefined, calc: any): [any, number][] {
  return (docs ?? []).map((d, di) => [d, di] as [any, number])
    .filter(([d]) => !(d.canShow && !calc.get(d.canShow).value))
}

function talentDocs(charSheet: any): [string, any[]][] {
  return Object.entries(charSheet.talent).map(([k, t]: any) => [k, t?.sections ?? []])
}

function compute(json: string): string {
  const req: Req & { only?: number[]; modes?: string[] } = JSON.parse(json)
  const modes = req.modes && req.modes.length ? req.modes : ['avg']
  const only = req.only ?? req.members.map((_, i) => i)
  const members = req.members.map((m, i) => {
    if (!only.includes(i)) return null
    const { charSheet, weaponSheet } = sheets(m)
    const calcs = modes.map((mode) => calcFor(req, HIT_MODE[mode], i))
    const calc = calcs[0]
    const stats: Record<string, number | null> = {}
    for (const k of STATS) stats[k] = num(calc.get((input.total as any)[k]).value)
    for (const e of ELES) stats[`${e}_dmg_`] = num(calc.get((input.total as any)[`${e}_dmg_`]).value)

    // Named formulas (info.path 'path_...'); stat-path fields are buffs, not hits.
    const rows: any[] = []
    const addDocs = (section: string, docs: any[], idOf: (di: number, fi: number) => string) => {
      for (const [doc, di] of shown(docs, calc))
        (doc.fields ?? []).forEach((f: any, fi: number) => {
          if (!f.node) return
          if (typeof f.canShow === 'function' && !f.canShow(calc)) return
          const info: any = calc.get(f.node).info ?? {}
          if (typeof info.path !== 'string' || !info.path.startsWith('path_')) return
          const row: any = {
            id: idOf(di, fi), section, name: (infoManager as any)[info.path]?.name ?? null,
            variant: info.variant ?? '', subVariant: info.subVariant ?? '', multi: info.multi ?? null,
          }
          calcs.forEach((c, n) => { row[modes[n]] = num(c.get(f.node).value) })
          rows.push(row)
        })
    }
    for (const [tk, docs] of talentDocs(charSheet)) addDocs(tk, docs, (di, fi) => `${tk}:${di}:${fi}`)
    addDocs('weapon', weaponSheet.document ?? [], (di, fi) => `weapon:${di}:${fi}`)
    for (const [name, node] of Object.entries(calc.getDisplay()['reaction'] ?? {}) as [string, any][]) {
      if (node.isEmpty || !((num(node.value) ?? 0) > 0)) continue
      const row: any = {
        id: `reaction:${name}`, section: 'reaction', name: null,
        variant: node.info?.variant ?? '', subVariant: node.info?.subVariant ?? '', multi: null,
      }
      calcs.forEach((c, n) => { row[modes[n]] = num(c.getDisplay()['reaction']?.[name]?.value) })
      rows.push(row)
    }
    return { stats, formulas: rows }
  })
  return JSON.stringify({ members })
}

function conditionals(json: string): string {
  const req: Req = JSON.parse(json)
  const out: any[] = []
  const seen = new Set<string>()
  const add = (docs: any[], calc: any, src: string, kind: string, section: string) => {
    for (const [doc] of shown(docs, calc)) {
      if (!doc.states) continue
      const st = typeof doc.states === 'function' ? doc.states(calc) : doc.states
      const teamBuff = !!doc.teamBuff
      const entries: any[] = doc.path
        ? [{ src, sheet: doc.path[0], name: doc.path[1], label: doc.name ?? null, teamBuff, kind, section,
             states: Object.entries(st).map(([k, v]: any) => ({ value: k, label: v.name ?? null })) }]
        : Object.entries(st).filter(([, v]: any) => v.path).map(([k, v]: any) => ({
            src, sheet: v.path[0], name: v.path[1], label: v.name ?? null, teamBuff, kind, section,
            states: [{ value: k, label: null }] }))
      for (const e of entries) {
        const id = `${e.sheet}|${e.name}`
        if (seen.has(id)) continue
        seen.add(id)
        out.push(e)
      }
    }
  }
  req.members.forEach((m, i) => {
    try {
      const calc = calcFor(req, 'avgHit', i), src = String(i)
      const { charSheet, weaponSheet } = sheets(m)
      for (const [tk, docs] of talentDocs(charSheet))
        try { add(docs, calc, src, 'char', tk) } catch (e) { /* one broken sheet must not fail the list */ }
      try { add(weaponSheet.document ?? [], calc, src, 'weapon', 'weapon') } catch (e) { /* as above */ }
      const count: Record<string, number> = {}
      for (const a of m.artifacts ?? []) count[a.set] = (count[a.set] ?? 0) + 1
      for (const [set, n] of Object.entries(count)) {
        const sheet: any = getArtSheet(set as any)
        for (const k of [2, 4]) {
          if (n < k) continue
          try { add(sheet?.setEffectDocument(k) ?? [], calc, src, 'artifact', `${set}:${k}`) } catch (e) { /* as above */ }
        }
      }
    } catch (e) { /* as above */ }
  })
  try {
    const calc = calcFor(req, 'avgHit', 0)
    for (const r of [...resonanceSheets, getMoonsignSheet(calc)] as any[]) {
      try {
        if (!r.canShow(calc)) continue
        add(r.sections ?? [], calc, '0', 'team', 'resonance')
      } catch (e) { /* as above */ }
    }
  } catch (e) { /* as above */ }
  return JSON.stringify(out)
}

function optimize(json: string): string {
  const req: Req & { target: { member: number; frames: { id: string; multiplier?: number }[] };
    minimums?: { key: string; value: number }[]; families: any[][][]; top?: number } = JSON.parse(json)
  const t = req.target.member, top = req.top ?? 5
  const key = req.members[t].char.key
  const { charSheet, weaponSheet } = sheets(req.members[t])
  const ui: any = (uiDataForTeam(teamData(req, 'avgHit', t) as any, 'F', key) as any)[key]!.target
  const workerData: any = ui.data[0]
  Object.assign(workerData, mergeData([workerData, dynamicData])) // mark art fields dynamic

  const resolve = (id: string): any => {
    const [a, b, c] = id.split(':')
    const node = a === 'reaction' ? workerData.display?.reaction?.[b]
      : a === 'weapon' ? weaponSheet.document?.[+b]?.fields?.[+c]?.node
      : charSheet.talent[a]?.sections?.[+b]?.fields?.[+c]?.node
    if (!node) throw new Error(`no formula ${id}`)
    return node
  }
  const targetNode = sum(...req.target.frames.map((f) => prod(f.multiplier ?? 1, resolve(f.id))))
  const mins = req.minimums ?? []
  const nodes = wrOptimize(
    [...mins.map((m) => (input.total as any)[m.key]), targetNode], workerData,
    ({ path: [p] }: any) => p !== 'dyn')
  const min = mins.map((m) => m.value - 1e-7)

  const best: { ids: string[]; value: number }[] = []
  let evaluated = 0, pruned = 0
  for (const family of req.families) {
    const slot = (list: any[]) => list.map((c) => {
      const { id, ...values } = c
      return { id, set: Object.keys(values).find((k) => values[k] === 1 && artSets.has(k)), values }
    })
    const arts: any = {
      base: {},
      values: Object.fromEntries(SLOTS.map((s, i) => [s, slot(family[i])])),
    }
    const { nodes: n2, arts: pre } = pruneAll(nodes, min, arts, top, {} as any,
      { pruneArtRange: true, pruneNodeRange: true })
    const slots: any[][] = Object.values(pre.values).sort((a: any, b: any) => a.length - b.length)
    let total = 1
    for (const s of slots) total *= s.length
    pruned += total
    if (!total) continue
    const f = precompute(n2, pre.base, (r: any) => r.path[1], slots.length)
    const buffer: any[] = new Array(slots.length)
    const walk = (i: number) => {
      if (i < 0) {
        const result = f(buffer)
        evaluated++
        if (!min.every((m, k) => m <= result[k])) return
        const value = result[min.length]
        if (best.length === top && value <= best[top - 1].value) return
        best.push({ ids: buffer.map((x) => x.id), value })
        best.sort((a, b) => b.value - a.value)
        if (best.length > top) best.length = top
        return
      }
      for (const a of slots[i]) { buffer[i] = a; walk(i - 1) }
    }
    walk(slots.length - 1)
  }
  return JSON.stringify({ builds: best, evaluated, pruned })
}

;(globalThis as any).LumensparGO = { compute, conditionals, optimize }

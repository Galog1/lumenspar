// Lumenspar's entry point into Genshin Optimizer's formula engine
// (libs/gi/formula, "pando"; MIT License, https://github.com/frzyc/genshin-optimizer).
// Bundled by tools/build_go_engine.py and run in Qt's QJSEngine.
//
//   LumensparGO.compute(json)      -> json   stats and every formula, per member
//   LumensparGO.conditionals(json) -> json   the conditionals a team can toggle
//
// Request: { members: [{ char: ICharacter, weapon: IWeapon,
//                        artifacts: [{ set, stats: [{ key, value }] }] }],
//            conditionals: { [src member]: { [sheet]: { [name]: value } } },
//            enemy: { level, res, amp, cata },
//            only: [member indices to compute] (default all),
//            modes: ['avg' | 'crit' | 'nonCrit'] (default ['avg']) }
// Each (member, mode) is one full calculation, about a second in QJSEngine,
// so callers ask only for what they show.
// Percent stats are fractions (0.466), as in GO.
import {
  artifactsData, charData, conditionalEntries, conditionals as allConds,
  enemyDebuff, genshinCalculatorWithEntries, own, ownBuff,
  pandoContextEntries, teamData, weaponData, withMember,
} from '@genshin-optimizer/gi/formula'

type Req = {
  members: { char: any; weapon: any; artifacts?: any[] }[]
  conditionals?: Record<string, Record<string, Record<string, number | string>>>
  enemy?: { level?: number; res?: number; amp?: string; cata?: string }
  only?: number[]
  modes?: string[]
}

const STATS = ['hp', 'atk', 'def', 'eleMas', 'critRate_', 'critDMG_', 'enerRech_', 'heal_']
const ELES = ['pyro', 'hydro', 'electro', 'cryo', 'anemo', 'geo', 'dendro', 'physical']

function entries(req: Req, active: string, critMode: string): any[] {
  const ids = req.members.map((_, i) => String(i))
  return [
    ...teamData(ids as any),
    ...pandoContextEntries({ memberKeys: ids as any, activeMember: active }),
    ...req.members.flatMap((m, i) =>
      withMember(String(i) as any, ...charData(m.char), ...weaponData(m.weapon),
        ...artifactsData(m.artifacts ?? []))),
    ...conditionalRows(req, ids),
    enemyDebuff.common.lvl.add(req.enemy?.level ?? 100),
    enemyDebuff.common.preRes.add(req.enemy?.res ?? 0.1),
    enemyDebuff.reaction.amp.add(req.enemy?.amp ?? ''),
    enemyDebuff.reaction.cata.add(req.enemy?.cata ?? ''),
    ownBuff.common.critMode.add(critMode),
  ]
}

// A conditional is set once, on its source. GO reads some conditionals per
// (source, destination), others with the source and/or destination ignored
// (e.g. "enemy frozen" ignores both), and the team listing does not say which;
// conditionals are read with `max`, so writing every combination is exact.
function conditionalRows(req: Req, ids: string[]): any[] {
  const rows: any[] = []
  for (const [src, sheets] of Object.entries(req.conditionals ?? {}))
    for (const [sheet, conds] of Object.entries(sheets))
      for (const [name, val] of Object.entries(conds)) {
        const targets: [string | null, string | null][] = [[src, null], [null, null]]
        for (const dst of ids) targets.push([src, dst], [null, dst])
        for (const [s, d] of targets)
          rows.push((conditionalEntries as any)(sheet, s, d)(name, val))
      }
  return rows
}

function member(req: Req, id: string, modes: string[]) {
  // Each member is computed as the active (on-field) character.
  const byMode: Record<string, any[]> = {}
  const stats: Record<string, number> = {}
  modes.forEach((mode, n) => {
    const calc = genshinCalculatorWithEntries(entries(req, id, mode))
    const mem = calc.withTag({ src: id } as any)
    if (n === 0) {
      for (const s of STATS) stats[s] = mem.compute((own.final as any)[s]).val
      for (const e of ELES) stats[`${e}_dmg_`] = mem.compute((own.final as any).dmg_[e]).val
    }
    byMode[mode] = mem.listFormulas(own.listing.formulas)
      .filter((f: any) => f.tag.qt === 'formula')
      .map((f: any) => ({ tag: f.tag, value: calc.compute(f).val }))
  })
  const first = byMode[modes[0]]
  const formulas = first.map((f: any) => {
    const row: any = {
      sheet: f.tag.sheet, name: f.tag.name, move: f.tag.move ?? '', ele: f.tag.ele ?? '',
      q: f.tag.q,
    }
    for (const mode of modes)
      row[mode] = (byMode[mode].find((g: any) => sameTag(g.tag, f.tag)) || {}).value
    return row
  })
  return { stats, formulas }
}

function sameTag(a: any, b: any): boolean {
  return a.sheet === b.sheet && a.name === b.name && a.q === b.q && a.qt === b.qt
}

function compute(json: string): string {
  const req: Req = JSON.parse(json)
  const modes = req.modes && req.modes.length ? req.modes : ['avg']
  const only = req.only ?? req.members.map((_, i) => i)
  return JSON.stringify({
    members: req.members.map((_, i) => (only.includes(i) ? member(req, String(i), modes) : null)),
  })
}

function conditionals(json: string): string {
  // The sheets a team touches: each member's character, weapon and artifact
  // sets, elemental resonance ("reso") and shared enemy/shield states ("static").
  const req: Req = JSON.parse(json)
  const out: any[] = []
  req.members.forEach((m, i) => {
    const sets = new Set((m.artifacts ?? []).map((a: any) => a.set))
    const sheets = [m.char.key, m.weapon.key, ...sets]
    for (const sheet of sheets) {
      const conds = (allConds as any)[sheet]
      if (!conds) continue
      for (const c of Object.values(conds) as any[]) out.push({ src: String(i), ...c })
    }
  })
  for (const sheet of ['reso', 'static'])
    for (const c of Object.values((allConds as any)[sheet] ?? {}) as any[])
      out.push({ src: '0', ...c })
  return JSON.stringify(out)
}

;(globalThis as any).LumensparGO = { compute, conditionals }

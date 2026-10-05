// SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
export type Step = { id: string; type: string; depends_on?: string[]; when?: string; [key: string]: unknown };
export type Placed = { id: string; type: string; layer: number; row: number };
export type Edge = { from: string; to: string; conditional: boolean };

export const STEP_TYPES = ['retrieve', 'generate', 'template', 'condition', 'extract', 'action', 'approval', 'handoff'] as const;

// Layer = longest path from "input". Rows are assigned in step order within a layer.
export function layout(steps: Step[]): { nodes: Placed[]; edges: Edge[]; layers: number; rows: number } {
  const layerOf = new Map<string, number>([['input', 0]]);
  const edges: Edge[] = [];
  for (const s of steps) {
    const deps = [...(s.depends_on ?? [])];
    if (s.when && !deps.includes(s.when)) deps.push(s.when);
    const parents = deps.length ? deps : ['input'];
    let layer = 1;
    for (const d of parents) {
      layer = Math.max(layer, (layerOf.get(d) ?? 0) + 1);
      edges.push({ from: d, to: s.id, conditional: d === s.when });
    }
    layerOf.set(s.id, layer);
  }
  const rowCount = new Map<number, number>();
  const nodes: Placed[] = [{ id: 'input', type: 'input', layer: 0, row: 0 }];
  rowCount.set(0, 1);
  for (const s of steps) {
    const layer = layerOf.get(s.id) ?? 1;
    const row = rowCount.get(layer) ?? 0;
    rowCount.set(layer, row + 1);
    nodes.push({ id: s.id, type: s.type, layer, row });
  }
  return {
    nodes,
    edges,
    layers: Math.max(...nodes.map((n) => n.layer)) + 1,
    rows: Math.max(...rowCount.values()),
  };
}

// The API requires each step's dependencies to appear before it. Returns an
// ordered copy, or null when the graph has a cycle or an unknown dependency.
export function topoOrder(steps: Step[]): Step[] | null {
  const done = new Set<string>(['input']);
  const out: Step[] = [];
  let pending = [...steps];
  while (pending.length) {
    const ready = pending.filter((s) => [...(s.depends_on ?? []), ...(s.when ? [s.when] : [])].every((d) => done.has(d)));
    if (!ready.length) return null;
    for (const s of ready) {
      done.add(s.id);
      out.push(s);
    }
    pending = pending.filter((s) => !done.has(s.id));
  }
  return out;
}

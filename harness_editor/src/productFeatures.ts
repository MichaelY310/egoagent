import evaluation from '../../product_features/evaluation.json';
import evolution from '../../product_features/evolution.json';
import research from '../../product_features/research.json';
import training from '../../product_features/training.json';
import deployment from '../../product_features/deployment.json';
import background from '../../product_features/background.json';
import coc from '../../product_features/coc.json';
import heartflow from '../../product_features/heartflow.json';
import remote from '../../product_features/remote.json';
type Feature = { id: string; enabled: boolean; depends: string[]; routes: string[]; flows: string[]; flow_patterns: string[] };
const flags: Record<string, Feature> = Object.fromEntries([evaluation, evolution, research, training, deployment, background, coc, heartflow, remote].map(item => [item.id, item]));
export function featureEnabled(id: string, seen: string[] = []): boolean {
  const item = flags[id];
  return Boolean(item?.enabled && !seen.includes(id) && item.depends.every(dep => featureEnabled(dep, [...seen, id])));
}
export function routeEnabled(route: string): boolean {
  return Object.values(flags).every(item => !item.routes.includes(route) || featureEnabled(item.id));
}
export function flowEnabled(name: string): boolean {
  return Object.values(flags).every(item => featureEnabled(item.id) || (!item.flows.includes(name) && !item.flow_patterns.some(pattern => {
    const regex = pattern.split('*').map(part => part.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('.*');
    return new RegExp(`^${regex}$`).test(name);
  })));
}

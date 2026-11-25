import { useEffect, useState } from 'react';
import * as api from '../api/client';
import { API_BASE } from '../api/runtime';
import allRecipes from '../cookbookCatalog.json';
import { flowEnabled, routeEnabled } from '../productFeatures';
import type { WorkbenchRoute } from '../workbenchSession';
import './CookbookRecipe.css';

interface Props {
  onNavigate: (destination: WorkbenchRoute) => void;
  onOpenHarness: (name: string) => void;
}
const destinations: Array<[WorkbenchRoute, string, string]> = [
  ['harness', 'Build · 编排助手', '选择 Flow，在右侧配置 Identity 与能力，保存版本后在 Chat 使用。'],
  ['identity', 'Identity · 定义行为', '配置模型、角色、Ego 与 Superego；不配置模型时继承全局设置。'],
  ['tools', '工具与 Skills · 复用能力', '查看工具来源与说明，在 IDE 打开源码；为 Identity 选择能力。'],
  ['sessions', 'Sessions · 管理项目', '打开、重命名、Fork 或合并会话；项目与对话历史分别保存。'],
  ['changes', 'Changes · 审阅改动', '检查 Agent 已应用的修改，逐段保留或拒绝。'],
  ['observe', '运行相簿 · 观察与回放', '查看 Flow 节点输入输出和历史运行；回放不会再次执行工具。'],
  ['tasks', 'Evaluate · 开发中', '任务环境与可复现评分；仅在对应开发分支开放。'],
  ['evolution', 'Improve · 开发中', '候选优化与证据验证；实验结果不等于稳定增益。'],
  ['settings', 'Settings · 连接模型', '设置模型服务、审批策略和诊断。API 密钥只保存在本地。'],
];

export default function StudioHome({ onNavigate, onOpenHarness }: Props) {
  const [workspace, setWorkspace] = useState('');
  const [error, setError] = useState('');
  const [available, setAvailable] = useState<Set<string>>(new Set());
  useEffect(() => {
    let current = true;
    Promise.all([api.getWorkspace(), fetch(`${API_BASE}/api/harnesses`).then(async response => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json() as Promise<string[]>;
    })]).then(([context, names]) => { if (current) { setWorkspace(context.name || context.workspace || ''); setAvailable(new Set(names)); } })
      .catch(reason => { if (current) setError(String(reason)); });
    return () => { current = false; };
  }, []);
  const recipes = allRecipes.filter(item => flowEnabled(item.name) && available.has(item.name));
  return <main className="studio-home">
    <section className="studio-home-hero"><div>
      <span className="studio-eyebrow">{workspace || 'Local workspace'}</span>
      <h1>你的代码助手，你定义的工作流。</h1>
      <p>在 Chat 处理当前项目，用 Build 定义助手，用运行相簿了解每一步。主产品只展示已开放的功能。</p>
    </div><div className="studio-home-actions">
      <button className="primary" onClick={() => onOpenHarness('code_agent_fast')}>打开推荐代码助手</button>
      <button onClick={() => onNavigate('settings')}>配置模型</button>
      <button onClick={() => onOpenHarness('cookbook_01_react')}>从最小 ReAct 开始</button>
    </div></section>
    {error && <div className="studio-home-error">连接失败：{error}</div>}
    <section className="studio-home-grid">{destinations.filter(([route]) => routeEnabled(route)).map(([route, title, detail]) =>
      <article className="studio-home-card" key={route}><header><h2>{title}</h2></header><p>{detail}</p>
        <button onClick={() => onNavigate(route)}>打开</button></article>)}</section>
    <section className="cookbook-catalog" aria-label="Cookbook 课程目录"><h2>循序渐进的 Flow 示例 · {recipes.length}</h2>
      <p>每关都有简短说明、输入示例和可观察的结果；尚未开放的课程及其依赖不展示。</p>
      <div className="cookbook-chapters">{[...new Set(recipes.map(item => item.chapter))].map(chapter => <details key={chapter}>
        <summary>{chapter}</summary>{recipes.filter(item => item.chapter === chapter).map(item =>
          <button key={item.name} onClick={() => onOpenHarness(item.name)}><b>{item.step} · {item.title}</b><span>{item.added}</span></button>)}
      </details>)}</div>
    </section>
  </main>;
}

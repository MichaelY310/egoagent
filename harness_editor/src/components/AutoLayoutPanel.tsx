import { useEffect, useRef, useState } from 'react';
import type { AutoLayoutOptions, LayoutMetrics } from '../graphAutoLayout';

type Props = {
  options: AutoLayoutOptions;
  report: { before: LayoutMetrics; after: LayoutMetrics } | null;
  onChange: (options: AutoLayoutOptions) => void;
  onApply: () => void;
};

const PRESETS: Array<{ id: string; label: string; detail: string; options: AutoLayoutOptions }> = [
  { id: 'compact', label: '紧凑', detail: '较短连线，适合小图', options: { compactness: 82, avoidance: 58, simplicity: 82 } },
  { id: 'balanced', label: '均衡', detail: '默认推荐', options: { compactness: 52, avoidance: 82, simplicity: 58 } },
  { id: 'clean', label: '最清晰', detail: '空间换取少交叉', options: { compactness: 24, avoidance: 100, simplicity: 34 } },
];

function metricDelta(label: string, before: number, after: number) {
  const improved = after < before;
  const unchanged = after === before;
  return <span className={improved ? 'improved' : unchanged ? '' : 'worse'} title={`${label}：整理前 ${before}，整理后 ${after}`}>
    <b>{label}</b><i>{before}</i><em>→</em><strong>{after}</strong>
  </span>;
}

export default function AutoLayoutPanel({ options, report, onChange, onApply }: Props) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as globalThis.Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') setOpen(false); };
    window.addEventListener('pointerdown', close);
    window.addEventListener('keydown', escape);
    return () => {
      window.removeEventListener('pointerdown', close);
      window.removeEventListener('keydown', escape);
    };
  }, [open]);

  const setValue = (field: keyof AutoLayoutOptions, value: number) => onChange({ ...options, [field]: value });
  const currentPreset = PRESETS.find((preset) => Object.entries(preset.options).every(([key, value]) => options[key as keyof AutoLayoutOptions] === value));

  return <div className="builder-auto-layout" ref={rootRef}>
    <button
      type="button"
      className={`builder-arrange-button ${open ? 'active' : ''}`}
      aria-haspopup="dialog"
      aria-expanded={open}
      data-auto-layout-trigger
      onClick={() => setOpen((value) => !value)}
      title="自动排列节点并为 Edge 避让节点、交叉与重叠"
    >自动整理 <small>{currentPreset?.label || '自定义'}</small><i>⌄</i></button>
    {open && <section className="auto-layout-popover" role="dialog" aria-label="自动整理 Flow 设置">
      <header><div><b>自动整理整个 Flow</b><small>分层、减少交叉，再为每条 Edge 独立避障</small></div><button type="button" onClick={() => setOpen(false)} aria-label="关闭">×</button></header>
      <div className="auto-layout-presets" aria-label="布局预设">
        {PRESETS.map((preset) => <button
          type="button"
          key={preset.id}
          className={currentPreset?.id === preset.id ? 'active' : ''}
          onClick={() => onChange(preset.options)}
          title={preset.detail}
        ><b>{preset.label}</b><small>{preset.detail}</small></button>)}
      </div>
      <div className="auto-layout-sliders">
        <label title="数值越高，节点和层之间距离越小">
          <span><b>紧凑度</b><output>{options.compactness}</output></span>
          <input type="range" min="0" max="100" value={options.compactness} onChange={(event) => setValue('compactness', Number(event.target.value))} />
          <small>宽松</small><small>紧凑</small>
        </label>
        <label title="数值越高，越愿意绕远来避免 Edge 交叉、重叠和穿过节点">
          <span><b>避让强度</b><output>{options.avoidance}</output></span>
          <input type="range" min="0" max="100" value={options.avoidance} onChange={(event) => setValue('avoidance', Number(event.target.value))} />
          <small>短路径</small><small>少交叉</small>
        </label>
        <label title="数值越高，控制点越少；降低后会允许更多绕行">
          <span><b>Edge 简洁度</b><output>{options.simplicity}</output></span>
          <input type="range" min="0" max="100" value={options.simplicity} onChange={(event) => setValue('simplicity', Number(event.target.value))} />
          <small>允许绕行</small><small>少控制点</small>
        </label>
      </div>
      {report && <div className="auto-layout-report" aria-label="上一次整理结果">
        <small>上一次整理的几何估算</small>
        <div>
          {metricDelta('穿节点', report.before.edgeNodeOverlaps, report.after.edgeNodeOverlaps)}
          {metricDelta('交叉', report.before.edgeCrossings, report.after.edgeCrossings)}
          {metricDelta('重线', report.before.edgeOverlaps, report.after.edgeOverlaps)}
          {metricDelta('控制点', report.before.controlPoints, report.after.controlPoints)}
        </div>
      </div>}
      <p>节点永不重叠。循环和回边优先走图外侧；普通前向边优先走层间走廊。复杂图无法保证数学意义上的零交叉，但会在当前参数下选择代价最低的确定性方案。</p>
      <footer><button type="button" className="btn btn-secondary" onClick={() => setOpen(false)}>取消</button><button type="button" className="btn btn-exec" data-auto-layout-apply onClick={() => { onApply(); setOpen(false); }}>整理并重新布线</button></footer>
    </section>}
  </div>;
}

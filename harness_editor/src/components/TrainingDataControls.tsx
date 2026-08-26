import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  exportTrainingDataset,
  getTrainingAnnotations,
  saveTrainingAnnotation,
  type TrainingAnnotation,
  type TrainingExportManifest,
} from '../api/client';

const button: React.CSSProperties = {
  border: '1px solid #3c3c3c',
  borderRadius: 4,
  background: '#252526',
  color: '#bdbdbd',
  padding: '3px 6px',
  cursor: 'pointer',
  fontSize: 10,
  lineHeight: 1.3,
  whiteSpace: 'nowrap',
  flexShrink: 0,
};

export function annotationKey(targetType: TrainingAnnotation['target_type'], targetId: string) {
  return `${targetType}:${targetId}`;
}

export function useSessionAnnotations(session: string) {
  const [annotations, setAnnotations] = useState<TrainingAnnotation[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const reload = useCallback(async () => {
    if (!session) { setAnnotations([]); return; }
    setLoading(true); setError('');
    try {
      const result = await getTrainingAnnotations({ session });
      setAnnotations(result.annotations);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [session]);

  useEffect(() => { void reload(); }, [reload]);
  const byTarget = useMemo(() => new Map(annotations.map((item) => [annotationKey(item.target_type, item.target_id), item])), [annotations]);
  const onSaved = useCallback((annotation: TrainingAnnotation) => {
    setAnnotations((current) => {
      const next = current.filter((item) => item.id !== annotation.id);
      return [...next, annotation];
    });
  }, []);
  return { annotations, byTarget, loading, error, reload, onSaved };
}

type FeedbackProps = {
  session: string;
  targetType: TrainingAnnotation['target_type'];
  targetId: string;
  sourceHash?: string;
  annotation?: TrainingAnnotation;
  onSaved?: (annotation: TrainingAnnotation) => void;
  compact?: boolean;
};

export function TrainingFeedback({ session, targetType, targetId, sourceHash, annotation, onSaved, compact = false }: FeedbackProps) {
  const [saving, setSaving] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const [tags, setTags] = useState('');
  const [note, setNote] = useState('');

  useEffect(() => {
    setTags((annotation?.tags || []).join(', '));
    setNote(annotation?.note || '');
  }, [annotation?.id, annotation?.updated_at]);

  const persist = async (patch: Partial<TrainingAnnotation>) => {
    setSaving(true); setError('');
    try {
      const result = await saveTrainingAnnotation({
        session,
        target_type: targetType,
        target_id: targetId,
        source_hash: sourceHash,
        rating: patch.rating ?? annotation?.rating ?? 'neutral',
        important: patch.important ?? annotation?.important ?? false,
        include_in_training: patch.include_in_training ?? annotation?.include_in_training ?? false,
        tags: patch.tags ?? annotation?.tags ?? [],
        note: patch.note ?? annotation?.note ?? '',
      });
      onSaved?.(result.annotation);
      return result.annotation;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
      return undefined;
    } finally {
      setSaving(false);
    }
  };

  const stop = (event: React.SyntheticEvent) => event.stopPropagation();
  return <div onClick={stop} onMouseDown={stop} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, position: 'relative', opacity: saving ? 0.65 : 1, flexShrink: 0 }}>
    <button type="button" disabled={saving} aria-label="点赞" title="好结果：可用于正向 SFT / KTO" onClick={() => void persist({ rating: annotation?.rating === 'up' ? 'neutral' : 'up' })} style={{ ...button, color: annotation?.rating === 'up' ? '#89d185' : '#888', background: annotation?.rating === 'up' ? '#17351f' : button.background }}>👍</button>
    <button type="button" disabled={saving} aria-label="点踩" title="坏结果：不进入正向 SFT，可用于 KTO 或与同 prompt 点赞结果组成 DPO" onClick={() => void persist({ rating: annotation?.rating === 'down' ? 'neutral' : 'down' })} style={{ ...button, color: annotation?.rating === 'down' ? '#f48771' : '#888', background: annotation?.rating === 'down' ? '#431f1f' : button.background }}>👎</button>
    <button type="button" disabled={saving} aria-label="标记重要" title="标记为重要样本" onClick={() => void persist({ important: !annotation?.important })} style={{ ...button, color: annotation?.important ? '#e2c08d' : '#888', background: annotation?.important ? '#3b321d' : button.background }}>★</button>
    <button type="button" disabled={saving} aria-label="加入训练集" title="显式加入下一次‘仅导出标注内容’的数据集" onClick={() => void persist({ include_in_training: !annotation?.include_in_training })} style={{ ...button, color: annotation?.include_in_training ? '#4fc1ff' : '#888', background: annotation?.include_in_training ? '#12354a' : button.background }}>{annotation?.include_in_training ? '✓ 数据集' : '+ 数据集'}</button>
    {!compact && <button type="button" disabled={saving} aria-label="编辑标注详情" title="标签与备注" onClick={() => setOpen((value) => !value)} style={button}>标注…</button>}
    {open && <div style={{ position: 'absolute', zIndex: 20, top: 28, right: 0, width: 300, padding: 10, background: '#1e1e1e', border: '1px solid #454545', borderRadius: 6, boxShadow: '0 8px 24px #0009' }}>
      <div style={{ color: '#d4d4d4', fontSize: 11, fontWeight: 600, marginBottom: 8 }}>训练标注详情</div>
      <label style={{ display: 'block', color: '#999', fontSize: 10, marginBottom: 8 }}>标签（逗号分隔）
        <input value={tags} onChange={(event) => setTags(event.target.value)} placeholder="bugfix, concise, tool-use" style={{ display: 'block', width: '100%', boxSizing: 'border-box', marginTop: 4, padding: '6px 7px', background: '#181818', color: '#d4d4d4', border: '1px solid #3c3c3c', borderRadius: 3, fontSize: 11 }} />
      </label>
      <label style={{ display: 'block', color: '#999', fontSize: 10 }}>备注
        <textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="为什么好/坏；后续训练需要注意什么" style={{ display: 'block', width: '100%', minHeight: 66, resize: 'vertical', boxSizing: 'border-box', marginTop: 4, padding: '6px 7px', background: '#181818', color: '#d4d4d4', border: '1px solid #3c3c3c', borderRadius: 3, fontSize: 11 }} />
      </label>
      <div style={{ display: 'flex', alignItems: 'center', marginTop: 8, gap: 6 }}>
        {error && <span style={{ color: '#f48771', fontSize: 9, flex: 1 }}>{error}</span>}
        <button type="button" style={{ ...button, marginLeft: 'auto' }} onClick={() => setOpen(false)}>取消</button>
        <button type="button" style={{ ...button, color: '#fff', background: '#0e639c', borderColor: '#1177bb' }} onClick={async () => {
          const saved = await persist({ tags: tags.split(',').map((value) => value.trim()).filter(Boolean), note });
          if (saved) setOpen(false);
        }}>保存</button>
      </div>
    </div>}
    {!open && error && <span title={error} style={{ color: '#f48771', fontSize: 9 }}>!</span>}
  </div>;
}

const formatOptions = [
  { id: 'conversation', title: '整段对话 SFT', description: 'OpenAI messages JSONL；适合聊天/指令微调。' },
  { id: 'message_sft', title: '单条回复 SFT', description: '只导出被选中的 assistant 回复及其前置上下文。' },
  { id: 'model_call_sft', title: '精确模型调用 SFT', description: '真实模型输入/输出与工具；同时生成 LLaMAFactory ShareGPT。' },
  { id: 'kto', title: 'KTO 单边偏好', description: '点赞/点踩直接成为 label，无需同 prompt 配对。' },
  { id: 'preference', title: 'DPO / ORPO 偏好对', description: '只配对同一 prompt 的直接点赞与点踩模型调用。' },
  { id: 'trajectory', title: '完整长轨迹', description: '全部事件、子 Agent、上下文替换与工具过程，用于 harness 学习。' },
  { id: 'verl', title: 'verl Rollout', description: '精确 prompt/response；赞踩映射人工奖励 ±1。' },
  { id: 'unary_feedback', title: '标注审计表', description: '保存所有标签、备注、赞踩和原目标，便于清洗/奖励建模。' },
] as const;

type TrainingPanelProps = {
  session: string;
  availableSessions: string[];
  annotations: TrainingAnnotation[];
  onSaved: (annotation: TrainingAnnotation) => void;
};

export function TrainingDataPanel({ session, availableSessions, annotations, onSaved }: TrainingPanelProps) {
  const sessionAnnotation = annotations.find((item) => item.target_type === 'session' && item.target_id === session);
  const [scope, setScope] = useState<'current' | 'all'>('current');
  const [selection, setSelection] = useState<'marked' | 'all'>('marked');
  const [formats, setFormats] = useState<Set<string>>(() => new Set(formatOptions.map((item) => item.id)));
  const [destination, setDestination] = useState('');
  const [includeReasoning, setIncludeReasoning] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState('');
  const [manifest, setManifest] = useState<TrainingExportManifest | null>(null);

  const toggleFormat = (id: string) => setFormats((current) => {
    const next = new Set(current);
    if (next.has(id)) next.delete(id); else next.add(id);
    return next;
  });
  const runExport = async () => {
    if (!formats.size) { setError('至少选择一种导出格式。'); return; }
    setExporting(true); setError(''); setManifest(null);
    try {
      const result = await exportTrainingDataset({
        sessions: scope === 'current' ? [session] : availableSessions,
        destination: destination || undefined,
        selection,
        formats: [...formats],
        include_reasoning: includeReasoning,
      });
      setManifest(result.manifest);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExporting(false);
    }
  };

  const counts = annotations.reduce((result, item) => {
    result.total += 1;
    if (item.rating === 'up') result.up += 1;
    if (item.rating === 'down') result.down += 1;
    if (item.important) result.important += 1;
    if (item.include_in_training) result.included += 1;
    return result;
  }, { total: 0, up: 0, down: 0, important: 0, included: 0 });

  return <div style={{ height: '100%', overflow: 'auto', padding: 18, background: '#1e1e1e', color: '#d4d4d4' }}>
    <div style={{ maxWidth: 900, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <div style={{ flex: 1 }}><h3 style={{ margin: 0, fontSize: 15 }}>训练数据工作台</h3><div style={{ color: '#858585', fontSize: 10, marginTop: 4 }}>原始轨迹不变；人工标注单独存储，导出时再组合。</div></div>
        <TrainingFeedback session={session} targetType="session" targetId={session} annotation={sessionAnnotation} onSaved={onSaved} />
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, minmax(90px, 1fr))', gap: 7, marginBottom: 15 }}>
        {([['已标注', counts.total, '#d4d4d4'], ['点赞', counts.up, '#89d185'], ['点踩', counts.down, '#f48771'], ['重要', counts.important, '#e2c08d'], ['入库', counts.included, '#4fc1ff']] as const).map(([label, value, color]) => <div key={label} style={{ background: '#181818', border: '1px solid #303030', borderRadius: 5, padding: '9px 10px' }}><div style={{ color: '#858585', fontSize: 9 }}>{label}</div><div style={{ color, fontSize: 18, marginTop: 2 }}>{value}</div></div>)}
      </div>

      <section style={{ background: '#181818', border: '1px solid #303030', borderRadius: 6, padding: 13, marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 9 }}>1. 选择范围</div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', color: '#bbb', fontSize: 11 }}>
          <label><input type="radio" checked={scope === 'current'} onChange={() => setScope('current')} /> 当前 Session</label>
          <label><input type="radio" checked={scope === 'all'} onChange={() => setScope('all')} /> 所有 Session（{availableSessions.length}）</label>
          <span style={{ width: 1, background: '#3c3c3c' }} />
          <label title="点赞、点踩、重要或显式加入数据集的内容"><input type="radio" checked={selection === 'marked'} onChange={() => setSelection('marked')} /> 仅标注内容（推荐）</label>
          <label title="显式导出所选 Session 的全部内容"><input type="radio" checked={selection === 'all'} onChange={() => setSelection('all')} /> 整个 Session</label>
        </div>
      </section>

      <section style={{ background: '#181818', border: '1px solid #303030', borderRadius: 6, padding: 13, marginBottom: 12 }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 9 }}>2. 选择训练投影</div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(260px, 1fr))', gap: 7 }}>
          {formatOptions.map((item) => <label key={item.id} style={{ display: 'flex', gap: 8, padding: 9, background: formats.has(item.id) ? '#132a3a' : '#1e1e1e', border: `1px solid ${formats.has(item.id) ? '#245b78' : '#303030'}`, borderRadius: 4, cursor: 'pointer' }}>
            <input type="checkbox" checked={formats.has(item.id)} onChange={() => toggleFormat(item.id)} />
            <span><span style={{ display: 'block', fontSize: 11, color: '#ddd' }}>{item.title}</span><span style={{ display: 'block', marginTop: 3, color: '#858585', fontSize: 9, lineHeight: 1.4 }}>{item.description}</span></span>
          </label>)}
        </div>
      </section>

      <section style={{ background: '#181818', border: '1px solid #303030', borderRadius: 6, padding: 13 }}>
        <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 9 }}>3. 保存</div>
        <input value={destination} onChange={(event) => setDestination(event.target.value)} placeholder="留空保存到 .egoagent/exports/training/<时间>，或输入绝对目录" style={{ width: '100%', boxSizing: 'border-box', background: '#1e1e1e', border: '1px solid #3c3c3c', color: '#d4d4d4', padding: '7px 8px', borderRadius: 3, fontSize: 11 }} />
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 9 }}>
          <label style={{ color: '#999', fontSize: 10 }}><input type="checkbox" checked={includeReasoning} onChange={(event) => setIncludeReasoning(event.target.checked)} /> 包含 reasoning（确认有权训练后再开）</label>
          <span style={{ color: '#666', fontSize: 9 }}>导出边界会再次过滤疑似 API Key / token / password</span>
          <button type="button" disabled={exporting} onClick={() => void runExport()} style={{ ...button, marginLeft: 'auto', color: '#fff', background: '#0e639c', borderColor: '#1177bb', padding: '6px 13px' }}>{exporting ? '正在导出…' : '生成训练数据'}</button>
        </div>
        {error && <div style={{ color: '#f48771', fontSize: 10, marginTop: 9 }}>{error}</div>}
        {manifest && <div style={{ marginTop: 10, padding: 10, background: '#102515', border: '1px solid #285b32', borderRadius: 4 }}>
          <div style={{ color: '#89d185', fontSize: 11, fontWeight: 600 }}>导出完成：{manifest.destination}</div>
          <div style={{ color: '#aaa', fontSize: 9, lineHeight: 1.7, marginTop: 5 }}>{Object.entries(manifest.counts).map(([name, count]) => `${name}: ${count}`).join(' · ')}</div>
          <div style={{ color: '#777', fontSize: 9, marginTop: 3 }}>Manifest: {manifest.manifest_path}</div>
        </div>}
      </section>
    </div>
  </div>;
}

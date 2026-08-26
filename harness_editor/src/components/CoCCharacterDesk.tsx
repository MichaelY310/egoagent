import { FormEvent, useEffect, useMemo, useState } from 'react';
import * as api from '../api/client';

interface Props {
  onOpenHarness: (name: string) => void;
}

const ITEMS = [
  ['flashlight', '手电筒'], ['notebook', '笔记本'], ['camera', '相机'],
  ['matches', '火柴'], ['wrench', '扳手'], ['rope', '绳索'],
  ['first_aid_kit', '急救包'], ['revolver', '.38 左轮'],
] as const;

const DEFAULT_SKILLS = { spot_hidden: 50, library_use: 40, listen: 40, firearms_handgun: 25, first_aid: 30, persuade: 35, psychology: 30, history: 20, mechanical_repair: 20 };
const DEFAULT_CHARACTERISTICS = { STR: 50, CON: 50, SIZ: 50, DEX: 50, APP: 50, INT: 60, POW: 60, EDU: 60 };

export default function CoCCharacterDesk({ onOpenHarness }: Props) {
  const [cards, setCards] = useState<api.CoCCharacterCard[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  const [form, setForm] = useState({
    identity_name: '', character_name: '', occupation: '调查记者', age: 30, backstory: '', traits: 'curious, cooperative', hp: 11, san: 60,
    luck: 50, equipment: ['flashlight', 'notebook'] as string[], skills: { ...DEFAULT_SKILLS }, characteristics: { ...DEFAULT_CHARACTERISTICS },
  });

  const refresh = () => api.listCoCCharacters().then(setCards).catch((error) => setMessage(error.message));
  useEffect(() => { void refresh(); }, []);
  const selected = useMemo(() => new Set(form.equipment), [form.equipment]);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true); setMessage('');
    try {
      await api.createCoCCharacter({
        identity_name: form.identity_name,
        character_name: form.character_name,
        occupation: form.occupation,
        age: form.age,
        backstory: form.backstory,
        personality_traits: form.traits.split(',').map((value) => value.trim()).filter(Boolean),
        stats: { hp: form.hp, hp_max: form.hp, san: form.san, san_max: 99, mp: Math.max(1, Math.floor(form.characteristics.POW / 5)), mp_max: Math.max(1, Math.floor(form.characteristics.POW / 5)), luck: form.luck, move: 8, build: 0, characteristics: form.characteristics },
        skills: form.skills,
        equipment: form.equipment,
      });
      setMessage('人物卡已保存为 Identity；装备 Tool 已同步，可以在任意 CoC Harness 中反复绑定。');
      setForm((current) => ({ ...current, identity_name: '', character_name: '' }));
      await refresh();
    } catch (error) {
      setMessage(error instanceof Error ? error.message : String(error));
    } finally { setBusy(false); }
  };

  return <main className="coc-desk">
    <section className="coc-desk-hero">
      <div><span className="studio-eyebrow">Play · Identity-backed</span><h1>人物卡就是 Identity</h1>
        <p>一次车卡，跨模组复用。HP、SAN、Luck、技能与装备保存在 Identity；KP 只能通过可审计事务修改这些游戏字段。获得物品会安装 Tool，失去物品会移除 Tool。</p></div>
      <div className="coc-desk-actions"><button className="primary" onClick={() => onOpenHarness('coc_lightless_beacon')}>开 Lightless Beacon</button><button onClick={() => onOpenHarness('coc_the_haunting')}>开 The Haunting</button></div>
    </section>

    <section className="coc-desk-grid">
      <form className="coc-sheet-form" onSubmit={submit}>
        <header><div><span className="studio-eyebrow">Create</span><h2>车一张调查员人物卡</h2></div><span className="coc-revision">永久保存</span></header>
        <label>Identity ID<input required pattern="[a-z][a-z0-9_]*" placeholder="lin_xia_card" value={form.identity_name} onChange={(e) => setForm({ ...form, identity_name: e.target.value })} /><small>小写字母、数字、下划线；这是绑定 Harness 时看到的名字。</small></label>
        <div className="coc-form-row"><label>角色名<input required placeholder="林夏" value={form.character_name} onChange={(e) => setForm({ ...form, character_name: e.target.value })} /></label><label>职业<input required value={form.occupation} onChange={(e) => setForm({ ...form, occupation: e.target.value })} /></label></div>
        <div className="coc-form-row triple"><label>HP<input type="number" min="1" max="99" value={form.hp} onChange={(e) => setForm({ ...form, hp: Number(e.target.value) })} /></label><label>SAN<input type="number" min="0" max="99" value={form.san} onChange={(e) => setForm({ ...form, san: Number(e.target.value) })} /></label><label>Luck<input type="number" min="0" max="100" value={form.luck} onChange={(e) => setForm({ ...form, luck: Number(e.target.value) })} /></label></div>
        <fieldset><legend>初始装备 · 每件装备对应一个 Identity Tool</legend><div className="coc-item-picker">{ITEMS.map(([id, label]) => <label key={id} className={selected.has(id) ? 'selected' : ''}><input type="checkbox" checked={selected.has(id)} onChange={() => setForm((current) => ({ ...current, equipment: selected.has(id) ? current.equipment.filter((item) => item !== id) : [...current.equipment, id] }))} /><b>{label}</b><small>{id}</small></label>)}</div></fieldset>
        <details className="coc-advanced-sheet"><summary>完整人物卡 · 属性、技能与背景</summary>
          <div className="coc-form-row"><label>年龄<input type="number" min="15" max="120" value={form.age} onChange={(e) => setForm({ ...form, age: Number(e.target.value) })} /></label><label>性格标签<input value={form.traits} onChange={(e) => setForm({ ...form, traits: e.target.value })} /><small>用英文逗号分隔，直接进入 Identity personality。</small></label></div>
          <label>背景<textarea rows={3} placeholder="重要经历、信念、关系与弱点" value={form.backstory} onChange={(e) => setForm({ ...form, backstory: e.target.value })} /></label>
          <h3>八项属性</h3><div className="coc-number-grid">{Object.entries(form.characteristics).map(([key, value]) => <label key={key}>{key}<input type="number" min="1" max="100" value={value} onChange={(e) => setForm({ ...form, characteristics: { ...form.characteristics, [key]: Number(e.target.value) } })} /></label>)}</div>
          <h3>常用技能</h3><div className="coc-number-grid skills">{Object.entries(form.skills).map(([key, value]) => <label key={key}>{key}<input type="number" min="0" max="100" value={value} onChange={(e) => setForm({ ...form, skills: { ...form.skills, [key]: Number(e.target.value) } })} /></label>)}</div>
        </details>
        <button className="primary" disabled={busy}>{busy ? '正在保存…' : '保存人物卡 Identity'}</button>
        {message && <div className="coc-form-message" role="status">{message}</div>}
      </form>

      <section className="coc-card-library">
        <header><div><span className="studio-eyebrow">Library</span><h2>可复用人物卡</h2></div><span>{cards.length} 张</span></header>
        <p className="coc-library-help">打开模组后，把人物卡拖到“人类调查员 / 调查员A / 调查员B”席位。场景位置留在 Session，人物成长与装备留在这里。</p>
        <div className="coc-card-list">{cards.map((card) => <article key={card.identity}>
          <header><div><b>{card.name}</b><small>{card.occupation} · {card.identity}</small></div><span className="coc-revision">rev {card.revision}</span></header>
          <div className="coc-stat-strip"><span><b>{String(card.derived.hp)}</b>HP</span><span><b>{String(card.derived.san)}</b>SAN</span><span><b>{String(card.derived.luck)}</b>Luck</span></div>
          <div className="coc-equipment">{Object.entries(card.equipment).map(([id, item]) => <span key={id} title={`Tool: coc_use_${id}`}>{String(item.label || id)}</span>)}{!Object.keys(card.equipment).length && <em>没有随身物品</em>}</div>
          {card.conditions?.length > 0 && <div className="coc-conditions">状态：{card.conditions.join(' · ')}</div>}
        </article>)}</div>
      </section>
    </section>
  </main>;
}

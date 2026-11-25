import { useEffect, useState } from 'react';
import type { HarnessConfig } from '../types';
import './CookbookRecipe.css';
import catalog from '../cookbookCatalog.json';

export default function CookbookRecipe({ recipe, disabled, onOpen }: {
  recipe: NonNullable<HarnessConfig['cookbook']>;
  disabled: boolean;
  onOpen: (name: string) => void;
}) {
  const [copied, setCopied] = useState('');
  const [exampleIndex, setExampleIndex] = useState(0);
  useEffect(() => { setExampleIndex(0); setCopied(''); }, [recipe.step]);
  const example = recipe.examples?.[exampleIndex];
  const input = example ? example.text + (example.repeat_text ? '\n' + example.repeat_text.repeat(Math.min(1000, Math.max(0, example.repeat || 0))) : '') : recipe.try;
  return <details className="cookbook-recipe" open>
    <summary><b>Cookbook {recipe.step} / {recipe.total} · {recipe.title}</b><span>本关说明与验收</span></summary>
    <div className="cookbook-recipe-body">
      <div className="cookbook-navigation">
        <label>课程目录
          <select aria-label="Cookbook 课程目录" disabled={disabled} value={catalog.find(item => item.step === recipe.step)?.name || ''}
            onChange={event => onOpen(event.target.value)}>
            {[...new Set(catalog.map(item => item.chapter))].map(chapter => <optgroup key={chapter} label={chapter}>
              {catalog.filter(item => item.chapter === chapter).map(item => <option key={item.name} value={item.name}>
                {String(item.step).padStart(2, '0')} · {item.title}
              </option>)}
            </optgroup>)}
          </select>
        </label>
        {recipe.based_on && <button disabled={disabled} onClick={() => onOpen(recipe.based_on!)}>
          基于 {catalog.find(item => item.name === recipe.based_on)?.title || recipe.based_on}
        </button>}
      </div>
      <p>{recipe.added}</p>
      <div className="cookbook-recipe-columns">
        <label>在 Chat 选择当前 Harness，然后试一试
          {recipe.examples && <select aria-label="Cookbook 示例步骤" value={exampleIndex}
            onChange={(event) => { setExampleIndex(Number(event.target.value)); setCopied(''); }}>
            {recipe.examples.map((item, index) => <option key={index} value={index}>{item.label}</option>)}
          </select>}
          <textarea aria-label="Cookbook 示例输入" readOnly value={input} rows={3} />
        </label>
        <div><b>到哪里看效果</b><p>{recipe.observe}</p>{recipe.notes && <small>{recipe.notes}</small>}</div>
      </div>
      <footer>
        <button onClick={async () => {
          try { await navigator.clipboard.writeText(input); setCopied('已复制'); }
          catch { setCopied('请选中上方文本复制'); }
        }}>复制示例</button><span role="status">{copied}</span>
        <small>各关独立可运行；新增能力基于标明的前置课程，不要求把全部功能堆在一个 Agent。</small>
        {recipe.previous && <button disabled={disabled} onClick={() => onOpen(recipe.previous!)}>← 上一关</button>}
        {recipe.next && <button disabled={disabled} onClick={() => onOpen(recipe.next!)}>下一关 →</button>}
      </footer>
    </div>
  </details>;
}

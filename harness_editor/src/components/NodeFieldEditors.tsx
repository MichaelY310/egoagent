import { useEffect, useState } from 'react';

import { API_BASE } from '../api/runtime';


/** Code editor for one harness-local Python node implementation. */
export function ScriptEditor({ harnessName, scriptName }: { harnessName: string; scriptName: string }) {
  const [code, setCode] = useState('def run(ctx):\n    response = ctx["response"]\n    # 处理逻辑\n    return {"response": response}\n');
  const [status, setStatus] = useState<'idle' | 'loading' | 'saved' | 'error'>('idle');

  useEffect(() => {
    if (!scriptName) return;
    setStatus('loading');
    fetch(`${API_BASE}/api/script/${harnessName}/${scriptName}`)
      .then((response) => response.ok ? response.json() : null)
      .then((data) => {
        if (data?.code) setCode(data.code);
        setStatus('idle');
      })
      .catch(() => setStatus('idle'));
  }, [harnessName, scriptName]);

  const save = async () => {
    if (!scriptName) return;
    setStatus('loading');
    try {
      const response = await fetch(`${API_BASE}/api/script/${harnessName}/${scriptName}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code }),
      });
      setStatus(response.ok ? 'saved' : 'error');
      window.setTimeout(() => setStatus('idle'), 2000);
    } catch {
      setStatus('error');
    }
  };

  if (!scriptName) return <p style={{ fontSize: 11, color: '#888' }}>先填写脚本名称</p>;

  return (
    <div style={{ marginTop: 4 }}>
      <textarea
        value={code}
        onChange={(event) => setCode(event.target.value)}
        rows={12}
        style={{
          width: '100%', fontFamily: 'monospace', fontSize: 11,
          background: '#0a1628', color: '#e0e0e0', border: '1px solid #1e3a5f',
          borderRadius: 4, padding: 8, resize: 'vertical',
        }}
      />
      <div style={{ display: 'flex', gap: 6, marginTop: 4, alignItems: 'center' }}>
        <button className="btn btn-primary btn-sm" onClick={save}>保存脚本</button>
        {status === 'saved' && <span style={{ fontSize: 10, color: '#4ade80' }}>已保存</span>}
        {status === 'error' && <span style={{ fontSize: 10, color: '#ff6b6b' }}>保存失败</span>}
      </div>
    </div>
  );
}


export function JsonField({
  value,
  onChange,
  placeholder = '{}',
  rows = 5,
}: {
  value: unknown;
  onChange: (value: any) => void;
  placeholder?: string;
  rows?: number;
}) {
  const [text, setText] = useState(JSON.stringify(value ?? {}, null, 2));
  const [error, setError] = useState('');

  useEffect(() => {
    setText(JSON.stringify(value ?? {}, null, 2));
    setError('');
  }, [value]);

  const commit = () => {
    try {
      onChange(JSON.parse(text || '{}'));
      setError('');
    } catch (caught: any) {
      setError(caught.message || 'JSON 格式错误');
    }
  };

  return (
    <>
      <textarea
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
        rows={rows}
        placeholder={placeholder}
        style={{ fontFamily: 'monospace', fontSize: 11 }}
      />
      {error && <span style={{ color: '#ff6b6b', fontSize: 10 }}>{error}</span>}
    </>
  );
}


export function ValueField({ value, onChange, placeholder = '值或 $ctx.path' }: {
  value: unknown;
  onChange: (value: unknown) => void;
  placeholder?: string;
}) {
  const display = typeof value === 'string' ? value : value === undefined ? '' : JSON.stringify(value);
  return (
    <input
      value={display}
      placeholder={placeholder}
      onChange={(event) => {
        const raw = event.target.value;
        try { onChange(JSON.parse(raw)); } catch { onChange(raw); }
      }}
    />
  );
}

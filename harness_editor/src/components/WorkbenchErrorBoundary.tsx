import { Component, type ErrorInfo, type ReactNode } from 'react';

type Props = { children: ReactNode };
type State = { error: Error | null };

/** Keep a malformed legacy artifact from turning the complete webview white. */
export default class WorkbenchErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('[EgoAgent Workbench] render failed', error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <main className="workbench-crash" role="alert">
        <div className="workbench-crash-card">
          <span>Workbench recovery</span>
          <h1>这个页面的数据无法安全渲染</h1>
          <p>界面已停止在恢复页，未执行保存或修改操作。重新加载后可继续使用；错误细节会保留在开发者日志中。</p>
          <pre>{this.state.error.message || String(this.state.error)}</pre>
          <button type="button" onClick={() => window.location.reload()}>重新加载 Workbench</button>
        </div>
      </main>
    );
  }
}

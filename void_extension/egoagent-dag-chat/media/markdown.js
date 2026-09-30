/* Shared by live Chat and history replay. Never rewrite the stored response. */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory(require('./vendor/markdown-it.umd.min.js'));
  } else {
    root.EgoMarkdown = factory(root.markdownit);
  }
})(typeof globalThis === 'object' ? globalThis : this, function (MarkdownIt) {
  'use strict';
  const md = new MarkdownIt({ html: false, linkify: true, breaks: true, typographer: false, maxNesting: 32 });
  const escape = md.utils.escapeHtml;
  const baseValidateLink = md.validateLink.bind(md);
  // Match the existing Chat trust boundary: no command:, file:, data:,
  // javascript:, relative navigation, or implicit remote resource loading.
  md.validateLink = (href) => /^https?:\/\//i.test(href) && baseValidateLink(href);
  const defaultLinkOpen = md.renderer.rules.link_open || ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options));
  md.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
    tokens[index].attrSet('target', '_blank');
    tokens[index].attrSet('rel', 'noopener noreferrer');
    return defaultLinkOpen(tokens, index, options, env, renderer);
  };
  // Model-supplied images are explicit links, not tracking pixels. Uploaded
  // attachments continue through Chat's separate trusted attachment renderer.
  md.renderer.rules.image = (tokens, index) => {
    const token = tokens[index];
    const label = escape(token.content || '图片');
    const href = token.attrGet('src') || '';
    return md.validateLink(href)
      ? `<a class="markdown-image-link" href="${escape(href)}" target="_blank" rel="noopener noreferrer">🖼 ${label}</a>`
      : label;
  };
  md.renderer.rules.table_open = () => '<div class="markdown-table" role="region" aria-label="表格（可横向滚动）" tabindex="0"><table>\n';
  md.renderer.rules.table_close = () => '</table></div>\n';
  for (const type of ['th_open', 'td_open']) {
    md.renderer.rules[type] = (tokens, index, options, env, renderer) => {
      const token = tokens[index];
      const alignment = /^text-align:(left|center|right)$/.exec(token.attrGet('style') || '');
      // VS Code's CSP disallows inline styles; use a fixed class allowlist.
      token.attrs = (token.attrs || []).filter(([name]) => name !== 'style');
      if (alignment) token.attrJoin('class', `align-${alignment[1]}`);
      if (type === 'th_open') token.attrSet('scope', 'col');
      return renderer.renderToken(tokens, index, options);
    };
  }

  // Streaming updates should parse the changing answer, not every old answer.
  // Bound by both count and character size so large trajectories cannot grow
  // a permanent unbounded HTML cache. Cache keys include the complete source.
  const cache = new Map();
  const MAX_ENTRIES = 96;
  const MAX_CHARS = 2 * 1024 * 1024;
  let cachedChars = 0;
  function render(value) {
    const source = String(value ?? '').replace(/\r\n?/g, '\n');
    if (cache.has(source)) {
      const html = cache.get(source);
      cache.delete(source);
      cache.set(source, html);
      return html;
    }
    const html = '<div class="markdown-body">' + md.render(source) + '</div>';
    const cost = source.length + html.length;
    if (cost <= MAX_CHARS) {
      cache.set(source, html);
      cachedChars += cost;
      while (cache.size > MAX_ENTRIES || cachedChars > MAX_CHARS) {
        const oldest = cache.keys().next().value;
        cachedChars -= oldest.length + cache.get(oldest).length;
        cache.delete(oldest);
      }
    }
    return html;
  }
  return Object.freeze({ render });
});

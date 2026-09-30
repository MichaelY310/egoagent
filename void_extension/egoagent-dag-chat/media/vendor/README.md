# Vendored Markdown parser

`markdown-it.umd.min.js`: unmodified browser UMD distribution of **markdown-it 15.0.2**, MIT.
Upstream: https://github.com/markdown-it/markdown-it
Documentation: https://markdown-it.github.io/markdown-it/

The matching upstream license is `markdown-it.LICENSE`. No CDN or runtime npm install is required in Windows, WSL, SSH, or desktop builds.

Source: npm `markdown-it@15.0.2`, `dist/browser/markdown-it.umd.min.js`.
Tarball integrity (SHA-512):
`q4IGxMv56jCqT4OCRCADBoDP3LO4MhmTXjFbphHPXs4g3j9Xg5RDnxqN8IF/3vIWEU+VCnUq+7JUg/cfy2E6Qw==`

To update, obtain an explicitly pinned release using `npm pack --ignore-scripts`, verify its npm integrity, copy the browser UMD file and license here, update this notice, and run `node --test tests/chat_markdown.test.cjs` plus the other Chat tests. Do not replace the bundle with a remote script URL.

The small first-party `../markdown.js` adapter disables source HTML, restricts link schemes, avoids automatic remote image requests, replaces table alignment styles with CSP-compatible classes, and bounds the render cache. Keep these constraints when updating the dependency.

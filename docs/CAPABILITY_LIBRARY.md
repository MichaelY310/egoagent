# Capability Library

The Capability Library lets an Agent discover a small number of relevant
Skills, Tools, Knowledge sources, Identities, and Harnesses without placing the
entire library in every prompt.

## Progressive disclosure

1. The Agent initially receives only a bounded set of essential schemas plus
   `search_capabilities` and `activate_capability`.
2. Search returns compact metadata: name, type, description, tags, scope,
   evidence, and a reason for the match.
3. Activation loads the selected Tool/Skill schema or Knowledge body into the
   current Agent. Identity and Harness results return safe selection guidance.
4. Creation is recommended only when retrieval confidence and query coverage
   are both weak.

This keeps token cost proportional to the capabilities used by a task, rather
than to the size of the repository.

## Index and ranking

`capability_registry.py` stores metadata and real usage events in
`.egoagent/capabilities.sqlite3`. It scans:

- repository and workspace `.environment` assets;
- Identity-local Skills, Tools, and Knowledge;
- canonical `capability_packs/`;
- Harness and Identity metadata;
- workspace `.agents/skills` and `.codex/skills`.

Search runs two independent retrievers:

- lexical retrieval preserves exact names, tags, paths, CJK phrases, and
  action-object intent such as `create_harness`;
- dense retrieval embeds the short query and capability metadata, then uses
  cosine similarity to recover synonyms and cross-language intent.

The default `auto` mode fuses both ranked lists with weighted Reciprocal Rank
Fusion (RRF). It then applies workspace scope, a conservative Wilson success
prior, modest popularity, and recent-success evidence. RRF uses ranks rather
than mixing provider-specific cosine values with lexical scores. Logical
`(kind, name)` duplicates are removed after fusion.

Vectors are cached in the same SQLite database by capability id, embedding
model, and content hash. Reindexing recomputes only changed capability cards.
The embedded document is bounded metadata; executable bodies are still loaded
only by activation.

The default implementation is local SQLite and requires no background search
service. `meilisearch_manager` remains a compatibility adapter for old callers;
it no longer starts a daemon.

## Embedding backends and fallback

`requirements.txt` installs FastEmbed's CPU/ONNX runtime. On first semantic
query the default multilingual model downloads about 220 MB into
`.egoagent/embedding-models`; later searches reuse both the model and SQLite
vectors. No GPU is required.

An OpenAI-compatible embedding endpoint can be selected without changing code:

```text
EGOAGENT_EMBEDDING_PROVIDER=openai-compatible
EGOAGENT_EMBEDDING_BASE_URL=https://provider.example/v1
EGOAGENT_EMBEDDING_MODEL=provider/model-name
EGOAGENT_EMBEDDING_API_KEY=...
```

`EGOAGENT_EMBEDDING_PROVIDER=fastembed` forces local embeddings;
`disabled` forces lexical-only operation. `auto` prefers a fully configured
remote endpoint, otherwise uses FastEmbed. Download, endpoint, cache, or rate
limit failures are returned as `fallback_reason` and never break lexical
lookup.

## Usage telemetry

Tool execution records activation, success/failure, runtime, and last-success
time automatically. Search impressions are separate from activations. Metrics
are local evidence used to rank and inspect capabilities; they are not uploaded
and should never be manually inflated.

## Workbench

Open **能力库** in the IDE Workbench to browse cards, choose **混合搜索**,
**仅语义**, or **仅关键词**, inspect lexical/semantic evidence, reindex, and
pin executable capabilities to the current workspace. The status line names
the active model or explains why the request fell back. A pin is stored in the workspace's
`.egoagent/pinned_capabilities.json` and is loaded by newly started Agents.

## Extension points

- A cross-encoder can rerank the bounded RRF candidate set when evaluation data
  justifies its extra latency. Keep lexical search as the offline fallback.
- Team registries can exchange metadata and immutable package identifiers; the
  actual content should still be activated on demand.
- Compatibility, permission, license, version, and evaluation fields can be
  added without changing the Agent tool contract.
- Negative evidence should be task-conditional. A capability that fails one
  environment must not be globally hidden without enough samples.

## Design references

- [Agent Skills progressive disclosure](https://agentskills.io/home) and the
  [Skill specification](https://agentskills.io/specification): metadata first,
  full instructions only after activation, supporting files on demand.
- [Model Context Protocol Registry](https://modelcontextprotocol.io/registry/about):
  standardized capability metadata and downstream/private registry patterns.
- [Meilisearch ranking rules](https://www.meilisearch.com/docs/resources/internals/ranking):
  an explicit lexical ranking pipeline; EgoAgent keeps a local deterministic
  fallback and adds workspace/evidence reranking.
- [OpenAI latest-model guide](https://developers.openai.com/api/docs/guides/latest-model):
  keep tools task-relevant and use bounded programmatic filtering, ranking,
  deduplication, and aggregation before model context.
- [Sentence Transformers semantic search](https://www.sbert.net/examples/sentence_transformer/applications/semantic-search/README.html):
  encode queries and documents into one vector space and retrieve by
  similarity; exact search is appropriate for this small catalog.
- [Elastic hybrid search](https://www.elastic.co/docs/solutions/search/hybrid-search):
  combine full-text and vector retrieval, with RRF as the recommended starting
  point.
- [FastEmbed supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/):
  lightweight ONNX models, including the multilingual model used by default.

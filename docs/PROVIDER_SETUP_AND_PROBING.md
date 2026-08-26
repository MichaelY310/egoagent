# Model providers and capability probing

EgoAgent keeps provider credentials in environment variables. Do not put keys in an Identity,
Harness, task, prompt, or tracked project file.

## Configure a provider

DeepSeek:

```powershell
$env:DEEPSEEK_API_KEY = "your-key"
$env:EGOAGENT_LLM_MODEL = "deepseek-v4-flash"
python start-all.py
```

SiliconFlow:

```powershell
$env:SILICONFLOW_API_KEY = "your-key"
$env:EGOAGENT_LLM_MODEL = "Qwen/Qwen3-8B"
python start-all.py
```

Ollama or another local OpenAI-compatible server does not require a real API key:

```powershell
$env:EGOAGENT_LLM_PROVIDER = "ollama"
$env:EGOAGENT_LLM_BASE_URL = "http://127.0.0.1:11434"
$env:EGOAGENT_LLM_MODEL = "qwen3:8b"
python start-all.py
```

Anthropic-compatible endpoints use:

```powershell
$env:EGOAGENT_LLM_PROVIDER = "anthropic_compatible"
$env:EGOAGENT_LLM_BASE_URL = "https://api.anthropic.com"
$env:EGOAGENT_LLM_MODEL = "your-model"
$env:EGOAGENT_LLM_API_KEY = "your-key"
python start-all.py
```

The ignored `.env.local` file accepts the same names for persistent local development. Process
environment variables take precedence over that file.

## Use a provider when Windows DNS is unavailable

EgoAgent has an application-local DNS fallback for HTTPS model providers. It is enabled in `auto`
mode by default: normal DNS is tried first, and a localhost-only CONNECT tunnel is started only when
the provider hostname cannot be resolved. The tunnel resolves the exact provider hostname through
direct UDP DNS and connects by IP while preserving the original TLS hostname and certificate check.
It does not change Windows DNS, the hosts file, or the system proxy, and it is not applied to web
searches or arbitrary application traffic.

Optional `.env.local` settings:

```dotenv
# auto (default), on, or off
EGOAGENT_LLM_APP_DNS_PROXY=auto

# Comma-separated direct DNS resolvers used by the localhost tunnel
EGOAGENT_LLM_DNS_SERVERS=223.5.5.5,119.29.29.29

# If you already run a local HTTP CONNECT proxy, use it for LLM requests only
# EGOAGENT_LLM_HTTPS_PROXY=http://127.0.0.1:7890
```

The tunnel listens only on `127.0.0.1`, permits `CONNECT` only to provider hostnames that EgoAgent
explicitly registers, and permits HTTPS port 443 only. API keys and request bodies remain inside the
end-to-end TLS connection and are not logged by the tunnel. Standard `HTTPS_PROXY`/`ALL_PROXY`
settings still take precedence when the user has configured one.

## Verify capabilities in Studio

1. Open `http://127.0.0.1:8880/studio/` or the Studio tab from Void.
2. Open **Settings**.
3. Under **Model provider**, click **Probe capabilities**.
4. Inspect health, per-check latency, usage, and the role badges.

The probe uses four short requests: text, stream, JSON, and tool use. It maps observed behavior to
the roles `chat`, `tool_use`, `edit`, `apply`, `autocomplete`, `embedding`, `rerank`, `vision`, and
`reasoning`. Unsupported roles are rejected before an AI request begins; Void keeps its deterministic
local completion/edit/review fallback available.

DeepSeek V4 Flash currently rejects explicit `tool_choice`. EgoAgent therefore leaves tool selection
on automatic for DeepSeek and omits the incompatible thinking extension on tool-bearing turns.
Reasoning remains enabled for ordinary reasoning requests.

## HTTP API

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/ai/status
Invoke-RestMethod -Method Post -ContentType application/json -Body '{}' http://127.0.0.1:8765/api/ai/probe
```

The status response exposes whether a key exists but never returns the key. It includes the most
recent health result, capabilities, latency checks, usage, retries, cache tokens, and safe failure
diagnostics.

## Run the credential-free conformance suite

```powershell
python tests/test_provider_conformance.py
```

The suite starts a localhost-only fault-injection server. It covers OpenAI and Anthropic message
translation, text, streaming, reasoning, JSON output, one and multiple tools, malformed arguments,
denied/failed tools, exact tool-call result pairing, retry-after/429, timeout, usage, cached tokens,
Ollama normalization, health reporting, and capability gating. It never reads or spends a real key.

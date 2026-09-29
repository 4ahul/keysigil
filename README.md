# KeySigil

Embeddable API key management SDK with LLM token budget tracking.

```python
from keysigil import KeyForge

kf = KeyForge("sqlite:///keys.db")
await kf.setup()

# Create key — plaintext shown once
result = await kf.create_key(
    name="Production",
    rate_limit={"requests": 100, "window": "1m"},
    token_budget={"monthly": 1_000_000},
    permissions=["models.invoke"],
)
print(result.plaintext)  # kf_live_abc123...

# Verify on every request
v = await kf.verify(result.plaintext)
print(v.valid, v.permissions, v.token_budget_remaining)

# Track LLM usage
await kf.track_usage(result.key.id, input_tokens=500, output_tokens=200, model="claude-sonnet-5-5")
```

## Install

```bash
pip install keysigil                    # core (SQLite)
pip install 'keysigil[cli]'             # + CLI
pip install 'keysigil[all]'             # everything
```

## CLI

```bash
keysigil init
keysigil create --name "my-key" --rate-requests 100 --monthly-tokens 500000
keysigil verify kf_live_xxx
keysigil list
keysigil usage key_xxx
keysigil rotate key_xxx
keysigil revoke key_xxx
```

## Storage backends

- **SQLite** (default) — dev / single-server
- **PostgreSQL** — `pip install 'keysigil[postgres]'`, use `postgresql://...` URL
- **Redis** — `pip install 'keysigil[redis]'`, for rate limiting

## FastAPI middleware

```python
from keysigil.middleware.fastapi import KeyForgeAuth

auth = KeyForgeAuth(kf, require_permissions=["models.invoke"])

@app.post("/chat", dependencies=[Depends(auth)])
async def chat(request: Request):
    key_id = request.state.key_id  # injected by middleware
```

## MCP server (LLM agents)

```bash
keysigil serve
```

Tools: `create_api_key`, `verify_api_key`, `list_api_keys`, `revoke_api_key`, `track_token_usage`, `get_usage_stats`

## Key design

- Format: `kf_live_<256-bit-random>` (Stripe pattern, enables GitHub secret scanning)
- Hash: SHA-256 (high-entropy keys; argon2 too slow for hot-path verification)
- Rate limiting: sliding window algorithm (Cloudflare-proven)
- Plaintext shown once at creation — never stored

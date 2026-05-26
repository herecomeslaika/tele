# DeepSeek API — Gateway Full Pipeline E2E Validation

## Test Date
2026-05-26 19:15 UTC+8

## Configuration
- Provider: DeepSeek (OpenAI-compatible)
- Endpoint: `https://api.deepseek.com/v1`
- Model: `deepseek-chat`
- Max tokens: 256
- Temperature: 0.7
- Timeouts: first_token=30s, token_interval=15s, total=120s, provider=60s

## Test Steps

### 1. Gateway Configuration
- GatewayApp initialized with DeepSeek provider
- Security: disabled
- Audit: enabled
- Routing: priority (single provider)

### 2. INVOKE → Streaming Pipeline
- Sent INVOKE envelope with prompt: "Say exactly: Hello from A2A Gateway!"
- Payload included `model: deepseek-chat`

### 3. STREAM_CHUNK Collection
- Received 7 STREAM_CHUNK messages
- First token latency: **1.117s**
- Full response: "Hello from A2A Gateway!"

### 4. STREAM_END Verification
- STREAM_END received at 1.261s
- Reason: `stop`
- Total tokens: 7

### 5. Session State
- Final state: **Done** (correct terminal state)

### 6. Heartbeat on Completed Session
- HEARTBEAT sent to DONE session
- Response: accepted with status `alive` and `last_seen` timestamp

## Results

| Metric | Value |
|--------|-------|
| First Token Latency | 1.117s |
| Total Duration | 1.261s |
| Stream Chunks | 7 |
| Finish Reason | stop |
| Session State | Done |
| Overall | **PASSED** |

## JSON Evidence
See `evidence/deepseek-e2e-validation.json` for machine-readable results.

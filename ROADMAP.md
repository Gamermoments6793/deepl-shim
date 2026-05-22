# Roadmap

Direction and planned work for New-Speak. Not a contract — items can be reprioritized, dropped, or replaced as the project's needs evolve.

## Near-term

### Expand the contextual translation window
Status: **planned**

The `/v2/translate-contextual` endpoint currently expects ±10 surrounding messages from the client (Vencord). Going to ±50 has two benefits:

1. **Better translation quality.** More context resolves more pronoun, sarcasm, in-joke, and reference ambiguity.
2. **Prompt caching becomes effective.** Claude Haiku 4.5's minimum cacheable prefix is 4096 tokens. ±10 Discord messages rarely hits that; ±50 typically does. With caching, rapid-fire translates in the same channel within a 5-minute window cost roughly 10× less on the input side.

The shim is already context-window agnostic — the client controls how many messages it sends. The change is in the Vencord plugin's `getContext()` function plus an optional `cache_control: {"type": "ephemeral"}` marker on the context block in `translate_contextual_one()` once context routinely clears 4K tokens.

Cost projection at ±50, ~200 translates/day, no caching: ~$1/day. With caching factored in: well under $1/day.

### Vencord client plugin
Status: **planned**

A custom fork of Vencord's `Translate` plugin that:

- Reads `±N` surrounding messages from Discord's local `MessageStore` on translate trigger.
- Maintains a per-channel "activated" set in Vencord's `DataStore` — channels where auto-translation is enabled. Activation triggers: user manually translates a message, or user sends an outgoing-translated message.
- Subscribes to Discord's `MESSAGE_CREATE` event. For incoming messages in activated channels, auto-translates and renders the translation inline under the original.
- Hooks `MessagePreSend`. For outgoing messages in activated channels, calls `/v2/translate-contextual` with `direction: "outgoing"` and target language inferred from context, then augments the outgoing message:
  ```
  <translated text>
  -# <original text>
  ```
- Settings panel: per-channel activate/deactivate, "clear all activated channels", target language for incoming.

Hosted as a Vencord user plugin (not upstreamed) — the upstream `Translate` plugin remains hard-coded to DeepL's endpoint.

## Medium-term

### Vencord upstream PR — custom endpoint URL
Status: **considering**

Add a settings field to upstream Vencord's `Translate` plugin allowing users to point it at a custom DeepL-compatible endpoint URL. This removes the need for the DNS-hijack + self-signed cert approach in setups like New-Speak. Mostly benefits the broader Vencord community, not this project directly.

### GitHub mirror
Status: **considering**

Self-hosted Forgejo is the canonical home of New-Speak (write access stays inside the Tailnet), but public read access via GitHub mirror would lower the friction for outside readers and search engines. One-way mirror, periodic push via cron.

## Longer-term

### Per-channel context persistence
Status: **not planned, here for discussion**

Currently each translate is stateless: the client sends ±N context every call. An alternative is per-channel server-side state, where the shim retains a sliding window per channel ID and the client just sends the target text + channel ID.

Trade-off: significantly more server-side privacy footprint (durable message storage), more complex client/server contract, but lower per-request bandwidth. Unlikely to be worth it for Discord-scale traffic — kept here as a known design alternative, not a planned change.

### Streaming responses
Status: **not planned**

Translation responses are short (~50–200 tokens). Streaming overhead would exceed the latency benefit. Likely never worth implementing for this workload.

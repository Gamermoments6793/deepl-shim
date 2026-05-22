# Changelog

All notable changes to this project are documented here.

This project loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). It does not currently use semantic versioning — there are no formal releases yet, and changes are tracked by commit.

## [Unreleased]

### Added
- **`POST /v2/translate-contextual` endpoint.** Accepts a `text`, optional `target_lang` (`"EN"`, `"ES"`, ..., or `"auto"` for outgoing direction), optional `source_lang` hint, a required `direction` (`"incoming"` or `"outgoing"`), and a `context` array of surrounding messages (`[{author, content}, ...]`). Claude uses the context to resolve ambiguity (pronouns, sarcasm, in-jokes, implied subjects).
- **Channel-language inference.** For outgoing direction with `target_lang: "auto"`, Claude infers the channel's primary language from the context messages and returns it in `translations[0].inferred_target_language`. Internal protocol uses a `[target=XX]` prefix on the model's output, parsed off before responding.
- **`CONTEXTUAL_SYSTEM_PROMPT`** for the new endpoint, separate from the existing single-message `SYSTEM_PROMPT`. Same translation style rules (preserve tone, slang, emoji, mentions) plus context-handling and direction-handling rules.

### Validation
- Rejects `target_lang: "auto"` with `direction: "incoming"` (400) — auto-inference requires outgoing context the user is responding to.
- Rejects non-list `context`, missing or non-string `text`, and direction values other than `"incoming"` / `"outgoing"`.
- Claude API errors return HTTP 502 (distinguishable from shim being down).

### Unchanged
- `/v2/translate` (single-message DeepL-compatible endpoint) untouched — existing Vencord installs keep working without changes.

## Initial commit

- Flask service impersonating DeepL Free `/v2/translate` API.
- Backed by Claude Haiku 4.5.
- TLS on port 443 with self-signed cert. Designed to be reached via DNS hijack (`api-free.deepl.com → 127.0.0.1`) so unmodified DeepL clients (notably Vencord's `Translate` plugin) work without code changes.
- `/v2/usage` returns a "never limited" response for clients that check quota.
- `/health` for monitoring.
- Logs translation **metadata only** (count, length, source/target lang) — never message content.

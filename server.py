#!/usr/bin/env nix-shell
#!nix-shell -i python3 -p "python3.withPackages (ps: with ps; [ anthropic flask ])"
"""
deepl-shim: a DeepL /v2/translate compatible HTTP service that uses Claude Haiku 4.5.

Vencord's Translate plugin (and any DeepL client) can point at this server as if it
were DeepL Free/Pro. The shim translates requests into Claude API calls.

Configuration via environment variables:
  ANTHROPIC_API_KEY     — required, your Anthropic API key
  DEEPL_SHIM_HOST       — bind address (default 127.0.0.1; do NOT bind 0.0.0.0)
  DEEPL_SHIM_PORT       — bind port    (default 443)
  DEEPL_SHIM_TLS_CERT   — TLS cert path (default ./certs/cert.pem)
  DEEPL_SHIM_TLS_KEY    — TLS key  path (default ./certs/key.pem)
"""
import os
import sys
import logging
from flask import Flask, request, jsonify
import anthropic

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not ANTHROPIC_API_KEY:
    print("ANTHROPIC_API_KEY not set", file=sys.stderr)
    sys.exit(1)

LISTEN_HOST = os.environ.get("DEEPL_SHIM_HOST", "127.0.0.1")
LISTEN_PORT = int(os.environ.get("DEEPL_SHIM_PORT", "443"))
TLS_CERT = os.environ.get("DEEPL_SHIM_TLS_CERT", "./certs/cert.pem")
TLS_KEY = os.environ.get("DEEPL_SHIM_TLS_KEY", "./certs/key.pem")
MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """You are a translation engine for casual Discord chat.

Given text and a target language, you return ONLY the translated text — no preamble, no explanation, no quotes, no language labels.

Rules:
- Preserve tone, register, and slang. If the input is casual chat with internet slang ("xd", "lol", "lmao", "tío", "coño", "vamos", etc.), the output should sound equally casual in the target language. Do NOT formalize.
- Preserve emoji, mentions (@user), channel links (#channel), and code blocks (`code`) verbatim.
- If a slang term doesn't translate, leave it as-is.
- Do not add quotation marks or formatting that wasn't in the original.
- If the input is already in the target language, return it unchanged.
- NEVER add commentary like "Translation:" or "Here is the translation".

Output the translated text directly with no surrounding content."""

CONTEXTUAL_SYSTEM_PROMPT = """You are a translation engine for casual Discord chat with full conversation context.

Each request includes:
- Surrounding messages from the same Discord channel (for context, oldest first)
- A direction: 'incoming' (translating a message someone else sent) or 'outgoing' (translating a message the user is about to send)
- A target language code, or 'auto' (only valid with outgoing — infer the channel's primary language from the context messages)
- The specific text to translate

Rules:
- Output ONLY the translated text — no preamble, explanation, quotes, or language labels.
- Preserve tone, register, and slang. Casual chat stays casual. Internet slang ("xd", "lol", "tío", "vamos") should sound equally casual in the target language. Do NOT formalize.
- Preserve emoji, mentions (@user), channel links (#channel), and code blocks (`code`) verbatim.
- Use the context to resolve ambiguity — pronouns, references, implied subjects, sarcasm, in-jokes.
- If the input is already in the target language, return it unchanged.
- NEVER add commentary like "Translation:" or "Here is the translation".

For outgoing direction with target='auto':
- Determine the channel's primary language from the context messages (look at what other people are speaking).
- Translate the text to that language.
- Prefix your output with a single line of the form `[target=XX]` where XX is the ISO 639-1 code (EN, ES, FR, DE, JA, etc.), then a newline, then the translated text.
- If the context is unclear or already matches the source language, default to English: `[target=EN]`.

For all other cases, output the translated text directly with no prefix."""

LANG_NAMES = {
    "EN": "English", "EN-US": "American English", "EN-GB": "British English",
    "ES": "Spanish", "FR": "French", "DE": "German", "IT": "Italian",
    "PT": "Portuguese", "PT-BR": "Brazilian Portuguese", "PT-PT": "European Portuguese",
    "JA": "Japanese", "KO": "Korean", "ZH": "Chinese", "NL": "Dutch",
    "PL": "Polish", "RU": "Russian", "TR": "Turkish", "SV": "Swedish",
    "DA": "Danish", "NO": "Norwegian", "FI": "Finnish", "CS": "Czech",
    "EL": "Greek", "HU": "Hungarian", "RO": "Romanian", "BG": "Bulgarian",
    "UK": "Ukrainian", "ID": "Indonesian", "AR": "Arabic",
}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
app = Flask(__name__)


def translate_one(text: str, target_lang: str, source_lang: str | None) -> str:
    target_name = LANG_NAMES.get(target_lang.upper(), target_lang)
    src_hint = f" (source: {LANG_NAMES.get(source_lang.upper(), source_lang)})" if source_lang else ""
    user_message = f"Target language: {target_name}{src_hint}\n\nText:\n{text}"

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    for block in response.content:
        if block.type == "text":
            return block.text.strip()
    return text


def _params():
    if request.is_json:
        d = request.get_json(silent=True) or {}
        texts = d.get("text")
        if isinstance(texts, str):
            texts = [texts]
        return texts, d.get("target_lang"), d.get("source_lang")
    texts = request.form.getlist("text") or request.args.getlist("text")
    target = request.form.get("target_lang") or request.args.get("target_lang")
    source = request.form.get("source_lang") or request.args.get("source_lang")
    return texts, target, source


@app.route("/v2/translate", methods=["POST", "GET"])
def translate():
    texts, target_lang, source_lang = _params()
    if not texts:
        return jsonify({"message": "Missing 'text' parameter"}), 400
    if not target_lang:
        return jsonify({"message": "Missing 'target_lang' parameter"}), 400

    app.logger.info(f"translate: {len(texts)} text(s), {source_lang or 'auto'} -> {target_lang}")

    translations = []
    for t in texts:
        try:
            translated = translate_one(t, target_lang, source_lang)
        except anthropic.APIError as e:
            app.logger.error(f"Claude API error: {e}")
            translated = t  # fallback: return original
        translations.append({
            "detected_source_language": (source_lang or target_lang).upper(),
            "text": translated,
        })

    return jsonify({"translations": translations})


def translate_contextual_one(
    text: str,
    target_lang: str,
    source_lang: str | None,
    direction: str,
    context: list,
) -> tuple[str, str | None]:
    """Returns (translated_text, inferred_target_lang_or_None)."""
    is_auto = direction == "outgoing" and target_lang.lower() == "auto"
    target_name = "infer from context" if is_auto else LANG_NAMES.get(target_lang.upper(), target_lang)
    src_hint = (
        f" (source hint: {LANG_NAMES.get(source_lang.upper(), source_lang)})"
        if source_lang else ""
    )

    if context:
        ctx_lines = [
            f"@{(m.get('author') or '?')}: {(m.get('content') or '')}"
            for m in context
        ]
        context_block = "\n".join(ctx_lines)
    else:
        context_block = "(no context messages provided)"

    user_msg = (
        f"Channel context (oldest first):\n{context_block}\n\n"
        f"Direction: {direction}\n"
        f"Target language: {target_name}{src_hint}\n\n"
        f"Translate this message:\n{text}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=CONTEXTUAL_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_msg}],
    )

    raw = ""
    for block in response.content:
        if block.type == "text":
            raw = block.text.strip()
            break

    inferred_target = None
    if raw.startswith("[target="):
        first_line, _, rest = raw.partition("\n")
        if first_line.endswith("]"):
            inferred_target = first_line[len("[target="):-1].strip().upper() or None
            raw = rest.strip()

    return raw, inferred_target


@app.route("/v2/translate-contextual", methods=["POST"])
def translate_contextual():
    d = request.get_json(silent=True) or {}
    text = d.get("text")
    target_lang = d.get("target_lang") or "auto"
    source_lang = d.get("source_lang")
    direction = d.get("direction") or "incoming"
    context = d.get("context") or []

    if not text or not isinstance(text, str):
        return jsonify({"message": "Missing or invalid 'text' parameter"}), 400
    if direction not in ("incoming", "outgoing"):
        return jsonify({"message": "'direction' must be 'incoming' or 'outgoing'"}), 400
    if direction == "incoming" and target_lang.lower() == "auto":
        return jsonify({"message": "'auto' target_lang is only valid for outgoing direction"}), 400
    if not isinstance(context, list):
        return jsonify({"message": "'context' must be a list"}), 400

    try:
        translated, inferred_target = translate_contextual_one(
            text, target_lang, source_lang, direction, context
        )
    except anthropic.APIError as e:
        app.logger.error(f"Claude API error: {e}")
        return jsonify({"message": "translation failed", "error": str(e)}), 502

    app.logger.info(
        f"translate-contextual: {direction}, {len(context)} ctx msgs, "
        f"{source_lang or 'auto'} -> {inferred_target or target_lang}"
    )

    return jsonify({"translations": [{
        "detected_source_language": (source_lang or "auto").upper(),
        "text": translated,
        "inferred_target_language": inferred_target,
    }]})


@app.route("/v2/usage", methods=["GET"])
def usage():
    # DeepL clients sometimes check usage. Return a "never limited" response.
    return jsonify({"character_count": 0, "character_limit": 999999999})


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "model": MODEL})


if __name__ == "__main__":
    ssl_context = (TLS_CERT, TLS_KEY) if os.path.exists(TLS_CERT) else None
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, ssl_context=ssl_context, threaded=True)

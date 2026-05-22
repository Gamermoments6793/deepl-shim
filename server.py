#!/usr/bin/env nix-shell
#!nix-shell -i python3 -p "python3.withPackages (ps: with ps; [ anthropic flask ])"
"""
deepl-shim: a DeepL /v2/translate compatible HTTP service that uses Claude Haiku 4.5.

Vencord's Translate plugin (and any DeepL client) can point at this server as if it
were DeepL Free/Pro. The shim translates requests into Claude API calls.

Configuration via environment variables:
  ANTHROPIC_API_KEY     — required, your Anthropic API key
  DEEPL_SHIM_HOST       — bind address (default 127.0.0.1; do NOT bind 0.0.0.0)
  DEEPL_SHIM_PORT       — bind port    (default 1188)
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
TLS_CERT = os.environ.get("DEEPL_SHIM_TLS_CERT", "/home/william/deepl-shim/certs/cert.pem")
TLS_KEY = os.environ.get("DEEPL_SHIM_TLS_KEY", "/home/william/deepl-shim/certs/key.pem")
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

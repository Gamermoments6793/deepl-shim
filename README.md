# New-Speak

A DeepL-API-compatible translation proxy that uses Claude (or any LLM)
to produce context-aware translations. Drop-in replacement for clients
like Vencord's Translate plugin — the client thinks it's calling DeepL,
the response comes from Claude.

## Why

Off-the-shelf machine-translation services (Google, DeepL) are tuned
for formal correctness. They miss slang, internet-speak, register, and
cultural context — exactly the things that matter when you're talking
to friends on Discord.

LLM-backed translation handles these well, but no chat client speaks
"OpenAI API" or "Anthropic API" natively. They all speak "DeepL API."

This shim is the bridge.

## Architecture

```
Discord client (Vencord plugin)
     │
     ▼  HTTPS POST /v2/translate
api-free.deepl.com  ← hijacked via /etc/hosts to 127.0.0.1
     │
     ▼
this Flask shim on :443 with self-signed cert
     │
     ▼  Anthropic API
Claude Haiku 4.5 (cheap, slang-aware)
     │
     ▼
translated text returned in DeepL response format
```

## Status

Working but rough. Used in production by exactly one person (me).
Not yet packaged for distribution. See [Setup](#setup) for the
do-it-yourself install.

## Setup

### 1. Configuration

Copy `env.template` to `~/.config/deepl-shim/env` and add your
Anthropic API key:

```bash
mkdir -p ~/.config/deepl-shim
cp env.template ~/.config/deepl-shim/env
chmod 600 ~/.config/deepl-shim/env
$EDITOR ~/.config/deepl-shim/env  # paste your Anthropic API key
```

### 2. Self-signed TLS cert

The shim needs to impersonate `api-free.deepl.com` over HTTPS, which
means a self-signed cert that your system + Node.js will trust.

```bash
mkdir -p certs
cd certs
openssl req -x509 -newkey rsa:4096 -sha256 -days 3650 -nodes \
  -keyout key.pem -out cert.pem \
  -subj "/CN=api-free.deepl.com" \
  -addext "subjectAltName=DNS:api-free.deepl.com,DNS:api.deepl.com,IP:127.0.0.1"
chmod 600 key.pem
```

### 3. System-level wiring

Three pieces, all platform-specific:

- **DNS hijack** — point `api-free.deepl.com` at `127.0.0.1` via
  `/etc/hosts` (Linux/macOS) or `C:\Windows\System32\drivers\etc\hosts`
  (Windows). Needs admin/root.
- **Trust the cert system-wide** — for Linux distros: copy `cert.pem`
  into `/usr/local/share/ca-certificates/` (Debian) or
  `/etc/pki/ca-trust/source/anchors/` (RHEL) and run
  `update-ca-certificates` / `update-ca-trust`. NixOS:
  `security.pki.certificateFiles = [ ./cert.pem ];` in configuration.nix.
- **Trust the cert for Node.js (Vesktop)** — `NODE_EXTRA_CA_CERTS`
  environment variable pointing at `cert.pem`. For Vesktop, the
  cleanest path is overriding the `.desktop` entry's `Exec=` line to
  prefix `env NODE_EXTRA_CA_CERTS=/path/to/cert.pem`.
- **Unprivileged port 443** — only needed if you can't run the shim
  as root. On Linux:
  `sysctl net.ipv4.ip_unprivileged_port_start=0`.

### 4. Run the shim

```bash
pip install anthropic flask
ANTHROPIC_API_KEY=$(grep ANTHROPIC_API_KEY ~/.config/deepl-shim/env | cut -d= -f2) \
  python3 server.py
```

For a real install, use the included `deepl-shim.service` systemd unit:

```bash
mkdir -p ~/.config/systemd/user
cp deepl-shim.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now deepl-shim.service
```

### 5. Verify

```bash
curl https://api-free.deepl.com/v2/translate \
  -d 'text=Hola tio, vamos a jugar?' \
  -d 'target_lang=EN'
```

Should return JSON containing a translation like
`"Hey bro, want to play?"`.

If cert validation fails, your system trust store isn't seeing the
cert — see step 3.

## Cost

Using Claude Haiku 4.5 at $1/MTok input + $5/MTok output:

- **Per message:** ~$0.0005 (a twentieth of a cent)
- **Casual chat (50 msg/day):** ~$0.50/month
- **Active auto-translate (1000 msg/day):** ~$10–15/month

## Configuration

The shim reads these env vars:

| Variable             | Default                                   |
| -------------------- | ----------------------------------------- |
| `ANTHROPIC_API_KEY`  | (required)                                |
| `DEEPL_SHIM_HOST`    | `127.0.0.1`                               |
| `DEEPL_SHIM_PORT`    | `443`                                     |
| `DEEPL_SHIM_TLS_CERT`| `./certs/cert.pem`                        |
| `DEEPL_SHIM_TLS_KEY` | `./certs/key.pem`                         |

## API parity

Implements the subset of DeepL's API that Vencord's Translate plugin
uses:

- `POST /v2/translate` — text + target_lang + source_lang (optional)
- `GET /v2/usage` — returns a stub "unlimited" response so clients
  don't complain
- `GET /health` — basic health check (non-standard, our own)

## Limitations

- Single-message translation only. No rolling conversation context
  yet — each message is translated in isolation.
- Auth header on incoming requests is ignored. The shim trusts
  whoever can reach it on localhost.
- Only tested with Vencord's Translate plugin on Vesktop. Other DeepL
  clients may need API extensions.

## TODO List

- Get a couple of good human programmers to closely look at code. 
  Around 100 lines of "server.py" and 20 lines of "deepl-shim.service". 
  Would be nice to have vetted code if more want to use it.
- Translate the project to other languages. Thinking about using what 
  I've built to automatically do this, and allow others proficient in 
  other languages to make manual changes when needed.
- Find a path towards mitigating the need to add a cert. 
  Most realistic option: submit a PR to Vencord adding a 
  "custom DeepL endpoint URL" setting. 
  That single 20-line change would obsolete the DNS-hijack + self-signed-cert + NODE_EXTRA_CA_CERTS pipeline entirely.
  Vencord is a mature project with tens of thousands of users, unlike this shim, that was prototyped with AI assistance.
  Any contribution upstream will need to be hand-typed and follow their formal review process.

## License

GPL-3.0-or-later — see [LICENSE](LICENSE).

Same license as Vencord, which this project is most useful alongside.
If you modify and redistribute, your changes must stay open under GPL.

## Acknowledgements

Built collaboratively with Claude Code over a chaotic ~6-hour debug
session that included a brief excursion into Vencord plugin
development, the discovery that Node.js maintains its own CA bundle
distinct from the system trust store, and one (1) successful
Spanish-to-English meme translation.

I am currently focusing myself on a path to improve in terms of systems administration, not making software.
If you find this tool useful and have suggestions towards improving things please let me know.

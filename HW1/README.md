# HW1: LLM-enabled features for Zulip

This repository is a Zulip development checkout extended with two LLM-powered
features:

- **Unread message recap** – a concise, AI-generated recap of everything you
  have not read yet, where every sentence links back to the messages it was
  based on.
- **Topic title improver** – right after you send a channel message, the
  recent history of that topic is checked for drift; if the conversation has
  moved on, Zulip suggests a better title that you can accept with one click.

See [`implementation.md`](implementation.md) for how they are built.

## 1. Set up the development environment

This is a standard Zulip dev checkout, so the official
[Vagrant setup guide](https://zulip.readthedocs.io/en/latest/development/setup-recommended.html)
applies unchanged:

```bash
git clone <this repository> zulip
cd zulip
vagrant up --provider=docker     # or: vagrant up
vagrant ssh
```

Inside the guest:

```bash
cd /srv/zulip
source .venv/bin/activate
```

Running directly on an Ubuntu host (without Vagrant) also works — run
`./tools/provision` once instead of `vagrant up`. Provisioning installs every
Python and JavaScript dependency the features need; the LLM client is the
`openai` package, which Zulip already depends on, so **no extra libraries
have to be installed**.

## 2. Provide an LLM API key (required)

Both features call an OpenAI-compatible chat-completions API. The development
settings are preconfigured for **Groq** with the `openai/gpt-oss-120b` model
([`zproject/dev_settings.py`](zproject/dev_settings.py#L238-L239)). Groq's
free tier is sufficient.

1. Create a free account at <https://console.groq.com/> and generate an API
   key (it starts with `gsk_`).
2. Put it in Zulip's development secrets file, which is created by
   provisioning and is listed in `.gitignore`, so it can never be committed:

   ```bash
   # inside the dev environment, from the repository root
   echo "topic_summarization_api_key = gsk_YOUR_KEY_HERE" >> zproject/dev-secrets.conf
   ```

   The file must contain a `[secrets]` header (provisioning already adds one).
3. Restart the dev server if it was already running, so it re-reads the file.

To use a different OpenAI-compatible provider, change
`TOPIC_SUMMARIZATION_MODEL` and `TOPIC_SUMMARIZATION_API_BASE` in
[`zproject/dev_settings.py`](zproject/dev_settings.py#L238-L239) (for example
`gpt-4o-mini` with `https://api.openai.com/v1`) and put that provider's key
under the same `topic_summarization_api_key` secret. The key is read from the
secrets file by `zproject/computed_settings.py`; it is never read from source
files or from Git.

If no key is configured, both endpoints return a clear
"temporarily unavailable" error and never contact a provider.

## 3. Run the server

```bash
./tools/run-dev
```

Open <http://localhost:9991/devlogin> and log in as any of the development
users (for example **King Hamlet**). The sample database already contains
unread messages and multi-message topics to try the features on.

## 4. Using the features

**Message recap**

1. In the left sidebar, hover over **Combined feed** and click its `⋮` menu.
2. Choose **Recap unread messages**.
3. A dialog shows a spinner while the recap is generated (about two seconds),
   then the recap. Every `#id` citation in the text and every entry in the
   "Unread messages" list is a link; clicking one closes the dialog and
   narrows the view to that exact message.

**Topic title improver**

1. Open any channel topic that has at least three messages and send a message
   that continues a *different* subject than the topic title suggests (or
   send a few such messages).
2. Your message is delivered immediately; the drift check runs in the
   background after the send.
3. If drift is detected, a **Suggested topic title** dialog appears showing
   the current title, the suggested one, and the model's reason. Click
   **Rename topic** to apply it to every message in the topic, or
   **Keep current title** to dismiss it. Nothing is renamed without your
   confirmation.

   To keep provider cost bounded, each topic is checked at most once every
   five minutes; you can lower `TOPIC_CHECK_COOLDOWN_SECONDS` in
   [`zerver/actions/llm_features.py`](zerver/actions/llm_features.py#L31)
   while experimenting.

## 5. Testing without the browser

Fetch an API key for a development user, then call the endpoints directly:

```bash
KEY=$(curl -s -X POST http://localhost:9991/api/v1/dev_fetch_api_key \
      --data-urlencode username=hamlet@zulip.com | python3 -c 'import sys,json;print(json.load(sys.stdin)["api_key"])')

# Recap of unread messages (summary is HTML, references are permalinks)
curl -s http://localhost:9991/api/v1/messages/recap -u hamlet@zulip.com:$KEY

# Drift check for one topic
curl -s -X POST http://localhost:9991/api/v1/topics/improve-title \
     -u hamlet@zulip.com:$KEY \
     --data-urlencode stream_id=11 --data-urlencode "topic_name=Website redesign feedback"
```

Backend unit tests (the provider is mocked, so no key is needed):

```bash
./tools/test-backend zerver.tests.test_llm_features
```

Static checks used for this work: `./tools/run-mypy`, `ruff check`, `eslint`,
`tsc --noEmit`, `prettier --check`, `stylelint` and `./tools/check-templates`.

## 6. Where the code lives

| Area | Files |
| --- | --- |
| LLM calls, link building, drift detection | `zerver/actions/llm_features.py` |
| HTTP endpoints | `zerver/views/llm_features.py`, `zproject/urls.py` |
| Backend tests | `zerver/tests/test_llm_features.py` |
| Recap UI | `web/src/message_summary.ts`, `web/templates/unread_message_recap.hbs`, `web/templates/popovers/left_sidebar/left_sidebar_all_messages_popover.hbs`, `web/src/left_sidebar_navigation_area_popovers.ts` |
| Title suggestion UI | `web/src/compose.ts`, `web/templates/topic_title_suggestion.hbs` |
| Styling | `web/styles/modal.css` |
| Model / endpoint configuration | `zproject/dev_settings.py` |

## Secrets

No credentials are committed. The only place a key is read from is
`zproject/dev-secrets.conf` (or `/etc/zulip/zulip-secrets.conf` in
production), both of which are outside version control.

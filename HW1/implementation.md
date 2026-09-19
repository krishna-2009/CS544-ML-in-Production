# Implementation

## Demo video

The demonstration video showing both HW1 features is available here:

[HW1 feature demonstration video](https://uic.zoom.us/rec/share/4RcxRMhkabRCPuWiSTAdG4KsycSdlrRAKvAxKMMX4dBPJXgk5ODsfdedhV1HCoXX.Ia0NeOD6XLnfj8F_?startTime=1789793596000)

Both features share one small LLM layer in
[`zerver/actions/llm_features.py`](zerver/actions/llm_features.py): an
OpenAI-compatible client built from Zulip's existing
`TOPIC_SUMMARIZATION_*` settings with a 20 s timeout and a single retry
([L41–53](zerver/actions/llm_features.py#L41-L53)), a `_complete()` helper
([L64–75](zerver/actions/llm_features.py#L64-L75)), and a tolerant JSON parser
that strips code fences ([L185–190](zerver/actions/llm_features.py#L185-L190)).
The model in use is Groq's `openai/gpt-oss-120b`
([`zproject/dev_settings.py` L238–239](zproject/dev_settings.py#L238-L239)); the
key comes only from the git-ignored secrets file. The views in
[`zerver/views/llm_features.py`](zerver/views/llm_features.py) turn every
provider failure (SDK errors, timeouts, rate limits, unparseable output) into a
clean API error instead of a 500 ([L20](zerver/views/llm_features.py#L20),
[L33–35](zerver/views/llm_features.py#L33-L35)). Fourteen backend tests with a
mocked provider live in
[`zerver/tests/test_llm_features.py`](zerver/tests/test_llm_features.py).

## Feature 1: Message recap

**Endpoint.** `GET /json/messages/recap` is registered in
[`zproject/urls.py` L438–441](zproject/urls.py#L438-L441) and served by
`get_unread_message_recap` ([views L28–36](zerver/views/llm_features.py#L28-L36)).

**Backend.** `generate_unread_recap`
([L193–251](zerver/actions/llm_features.py#L193-L251)) selects the caller's
unread messages with Zulip's own `UserMessage.where_unread()` flag predicate,
oldest first, capped at 100 (`MAX_RECAP_MESSAGES`) so worst-case latency and
token cost are bounded; the response reports `truncated` when the cap hits.
Each message is sent to the model as `{id, sender, topic, content}` with
content clipped to 2 000 characters. If there is nothing unread, no provider
call is made.

**How links are created.** The prompt asks for structured output,
`{"recap": [{"text": …, "message_ids": […]}]}`, so citations arrive as
integers rather than as free-form punctuation
([L214–229](zerver/actions/llm_features.py#L214-L229)). Before the call,
`build_message_links` ([L78–111](zerver/actions/llm_features.py#L78-L111))
computes a permalink for every candidate message using Zulip's canonical
helpers: `encode_channel` / `encode_hash_component` produce
`#narrow/channel/<id>-<name>/topic/<topic>/near/<message_id>` for channel
messages, and `direct_message_group_narrow_url` + `/near/<id>` for DMs.
Display names are fetched in one `bulk_fetch_display_recipients` call, so a
100-message recap costs five database queries, not a hundred.
`render_recap_markdown` ([L137–173](zerver/actions/llm_features.py#L137-L173))
then appends `[#id](link)` for each cited id **that exists in that map** —
an id the model invents is silently dropped and can never become a link. If a
model ignores the JSON format, `linkify_citations`
([L114–134](zerver/actions/llm_features.py#L114-L134)) falls back to scanning
the prose for `[#12]`, `[12, 15]` or `` and applies the same allow-list.
The Markdown is rendered to HTML with Zulip's `markdown_convert`, exactly as
the built-in topic-summary feature does
([L235–237](zerver/actions/llm_features.py#L235-L237)), and the response also
carries a `references` array (id, sender, topic, link) for every message that
was summarised. Across eight live runs against Groq every recap contained
8–14 working links.

**Frontend.** A **Recap unread messages** item is added to the Combined feed
`⋮` menu
([template L3–8](web/templates/popovers/left_sidebar/left_sidebar_all_messages_popover.hbs#L3-L8),
[handler L247–250](web/src/left_sidebar_navigation_area_popovers.ts#L247-L250)).
`get_unread_message_recap` in
[`web/src/message_summary.ts` L85–153](web/src/message_summary.ts#L85-L153)
opens a `dialog_widget` modal, shows Zulip's loading spinner while the request
runs, validates the response with `zod`, renders
[`unread_message_recap.hbs`](web/templates/unread_message_recap.hbs) (the
summary plus a scrollable reference list, styled in
[`modal.css`](web/styles/modal.css)), and shows an error message if the
provider fails. Clicking any link closes the modal, and because the links are
same-origin `#narrow/…/near/<id>` fragments, Zulip's router narrows straight
to the message without a reload.

## Feature 2: Topic title improver

**Endpoint.** `POST /json/topics/improve-title` (`stream_id`, `topic_name`)
is registered at [`zproject/urls.py` L442–445](zproject/urls.py#L442-L445) and
served by `improve_topic_title`
([views L39–53](zerver/views/llm_features.py#L39-L53)).

**Backend.** `suggest_topic_title`
([L261–333](zerver/actions/llm_features.py#L261-L333)) loads the newest 20
messages of the topic that the caller actually received (the `usermessage`
join doubles as an access check), requires at least three, and asks the model
for strict JSON `{drifted, suggested_title, reason}`. The result is validated:
`drifted` must be literally `true`, the title must be a non-empty string and
is truncated to 60 characters, and a missing reason gets a default. On a live
test the on-topic control thread returned `drifted: false` and the drifted
thread returned `"Production database disk space alert and runbook"` with a
correct explanation, each in under a second.

**Latency.** The check is fired by the client *after* the send succeeds
([`compose.ts` L168–170](web/src/compose.ts#L168-L170)), so the model round
trip never delays message delivery, and the user still has the context when a
suggestion appears. Input is bounded (20 messages × 2 000 chars), the client
has a 20 s timeout, and retries are capped at one because the SDK honours
`Retry-After` on 429s (Groq asks for 30 s+), which would otherwise hang an
interactive request.

**Cost.** Every channel message would otherwise cost one model call. A
per-topic cooldown in memcached
([L254–258](zerver/actions/llm_features.py#L254-L258),
[L274–276, L297](zerver/actions/llm_features.py#L274-L297)) makes the number
of calls proportional to *active topics per five minutes* instead of message
volume; the key is claimed before the call so a burst of sends cannot start
several concurrent requests, and it is released if the call fails
([L317–319](zerver/actions/llm_features.py#L317-L319)) so a transient error does
not silence the feature. Topics with fewer than three messages are skipped
without a call. The dev settings carry the model's per-token prices so Zulip's
existing AI-cost accounting can be attached.

**Scalability.** Both features are stateless and add no schema, so they scale
with the web tier; shared state is only the memcached cooldown. At Zulip scale
I would move the drift check into a queue worker fed by the message-send path
(deduplicating per topic), cache results per `(topic, last_message_id)`, add a
per-user/realm token budget and a circuit breaker, and let organisations opt in
per channel.

**Frontend.** `suggest_topic_title` in
[`compose.ts` L178–222](web/src/compose.ts#L178-L222) posts to the endpoint;
errors are ignored (a background feature should never interrupt sending).
When `drifted` is true it opens a modal from
[`topic_title_suggestion.hbs`](web/templates/topic_title_suggestion.hbs)
showing the reason, the current and suggested titles, and a warning that
renaming moves every message. **Rename topic** issues Zulip's standard
`PATCH /json/messages/<id>` with `propagate_mode=change_all`
([L209–218](web/src/compose.ts#L209-L218)) — the same code path as manual
renames, so permissions and event propagation are unchanged; **Keep current
title** does nothing. A suggestion is never applied automatically.

## Limitations

Model output is non-deterministic; the allow-list guarantees links are real
but not that the prose is complete. Message content is sent to a third-party
provider, which needs a privacy review and per-organisation opt-in before
production use. Muted channels and topics are currently included in recaps.

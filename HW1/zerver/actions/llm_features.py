import hashlib
import json
import re
from typing import Any, Literal

from django.conf import settings
from openai import OpenAI
from openai.types.chat import ChatCompletionMessageParam

from zerver.lib.cache import cache_delete, cache_get, cache_set
from zerver.lib.display_recipient import bulk_fetch_display_recipients
from zerver.lib.markdown import markdown_convert
from zerver.lib.url_encoding import (
    direct_message_group_narrow_url,
    encode_channel,
    encode_hash_component,
)
from zerver.models import Message, Recipient, UserMessage, UserProfile

# Bounds on how much conversation we are willing to send to the provider in a
# single request.  These directly cap worst-case latency and per-request cost.
MAX_RECAP_MESSAGES = 100
MAX_TOPIC_MESSAGES = 20
MAX_CONTENT_LENGTH = 2000
MAX_SUGGESTED_TITLE_LENGTH = 60

# A topic needs some sustained discussion before "drift" is a meaningful
# question to ask, and we do not want to pay for an LLM call on every single
# message sent to a busy topic.
MIN_TOPIC_MESSAGES = 3
TOPIC_CHECK_COOLDOWN_SECONDS = 300

# The recap prompt asks the model to cite messages as [#12345]; we rewrite
# those citations into Markdown links to the original messages.  Models are
# not perfectly obedient about the format (gpt-oss variously produces [#12],
# [12], [86, 96] and 【12†L1-L3】), so we accept any bracketed group and pull
# the message ids out of it.
CITATION_RE = re.compile(r"\[([#\d,\s]+)\]|【([^】]*)】")


def _get_client() -> OpenAI:
    if settings.TOPIC_SUMMARIZATION_MODEL is None or settings.TOPIC_SUMMARIZATION_API_KEY is None:
        raise RuntimeError("AI features are not configured")
    # Both features are triggered by a user action, so we would rather fail
    # fast with a clear error than keep a request open for a long time.  The
    # SDK honours Retry-After on 429 responses (Groq's free tier asks for
    # 30s+), so more than a single retry can turn into a very long wait.
    return OpenAI(
        api_key=settings.TOPIC_SUMMARIZATION_API_KEY,
        base_url=settings.TOPIC_SUMMARIZATION_API_BASE,
        timeout=20.0,
        max_retries=1,
    )


def _make_message(
    content: str, role: Literal["user", "system"] = "user"
) -> ChatCompletionMessageParam:
    if role == "system":
        return {"content": content, "role": "system"}
    return {"content": content, "role": "user"}


def _complete(messages: list[ChatCompletionMessageParam]) -> str:
    model = settings.TOPIC_SUMMARIZATION_MODEL
    assert model is not None
    response = _get_client().chat.completions.create(
        model=model,
        messages=messages,
        **settings.TOPIC_SUMMARIZATION_PARAMETERS,
    )
    content = response.choices[0].message.content
    if not content:
        raise RuntimeError("The AI provider returned an empty response")
    return content.strip()


def build_message_links(user_profile: UserProfile, messages: list[Message]) -> dict[int, str]:
    """Map each message id to a permalink that narrows to that message.

    Zulip's web app navigates to a single message via a URL fragment of the
    form #narrow/channel/<id>-<name>/topic/<topic>/near/<message_id>, so we
    build the links out of the same encoding helpers the rest of the codebase
    uses rather than formatting the slugs by hand.  Display recipients are
    fetched in bulk so that a 100-message recap does not issue 100 queries.
    """
    display_recipients = bulk_fetch_display_recipients(
        {
            (message.recipient_id, message.recipient.type, message.recipient.type_id)
            for message in messages
        }
    )

    links = {}
    for message in messages:
        display_recipient = display_recipients[message.recipient_id]
        if message.recipient.type == Recipient.STREAM:
            assert isinstance(display_recipient, str)
            links[message.id] = (
                f"{user_profile.realm.url}/#narrow/channel/"
                f"{encode_channel(message.recipient.type_id, display_recipient)}"
                f"/topic/{encode_hash_component(message.topic_name())}"
                f"/near/{message.id}"
            )
        else:
            assert not isinstance(display_recipient, str)
            base_url = direct_message_group_narrow_url(
                user=user_profile, display_recipient=display_recipient
            )
            links[message.id] = f"{base_url}/near/{message.id}"
    return links


def linkify_citations(summary: str, links: dict[int, str]) -> str:
    """Turn the model's citations into Markdown links to the cited messages.

    The model only ever emits message ids, never URLs, so it cannot invent a
    link to somewhere unexpected.  A citation for an id we did not supply is
    dropped rather than rendered, so a hallucinated reference never becomes a
    clickable link.
    """

    def replace(match: re.Match[str]) -> str:
        cited = match.group(1) if match.group(1) is not None else match.group(2)
        rendered = [
            f"[#{message_id}]({links[message_id]})"
            for message_id in (int(token) for token in re.findall(r"\d+", cited))
            if message_id in links
        ]
        if not rendered:
            return ""
        return " " + " ".join(rendered)

    return CITATION_RE.sub(replace, summary).strip()


def render_recap_markdown(raw_response: str, links: dict[int, str]) -> str:
    """Build the recap Markdown, with a link for every cited message.

    The prompt asks for JSON of the form
    {"recap": [{"text": "...", "message_ids": [12, 15]}, ...]}, so the
    citations arrive as integers rather than as free-form punctuation and we
    can attach the links ourselves.  If the model ignores the format and
    replies in prose, we fall back to scanning that prose for bracketed ids.
    Either way, only ids that belong to the messages we supplied become links.
    """
    try:
        parsed = _parse_json_response(raw_response)
    except (ValueError, RuntimeError):
        return linkify_citations(raw_response, links)

    items = parsed.get("recap")
    if not isinstance(items, list):
        return linkify_citations(raw_response, links)

    sentences = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str) or not text.strip():
            continue
        cited_ids = item.get("message_ids", [])
        citations = [
            f"[#{message_id}]({links[message_id]})"
            for message_id in cited_ids
            if isinstance(message_id, int) and message_id in links
        ]
        sentences.append(" ".join([text.strip(), *citations]))

    if not sentences:
        return linkify_citations(raw_response, links)
    return "\n\n".join(sentences)


def _message_context(message: Message) -> dict[str, Any]:
    return {
        "id": message.id,
        "sender": message.sender.full_name,
        "topic": message.topic_name() if message.is_channel_message else "",
        "content": message.content[:MAX_CONTENT_LENGTH],
    }


def _parse_json_response(content: str) -> dict[str, Any]:
    content = content.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise RuntimeError("The AI provider returned an invalid JSON object")
    return parsed


def generate_unread_recap(user_profile: UserProfile) -> dict[str, Any]:
    unread_ids = list(
        UserMessage.objects.filter(user_profile=user_profile)
        .extra(where=[UserMessage.where_unread()])  # noqa: S610
        .order_by("message_id")
        .values_list("message_id", flat=True)[:MAX_RECAP_MESSAGES]
    )
    messages = list(
        Message.objects.filter(id__in=unread_ids, realm=user_profile.realm)
        .select_related("sender", "recipient")
        .order_by("id")
    )
    if not messages:
        return {
            "summary": "<p>You have no unread messages.</p>",
            "references": [],
            "truncated": False,
        }

    links = build_message_links(user_profile, messages)
    context = json.dumps([_message_context(message) for message in messages])
    raw_response = _complete(
        [
            _make_message(
                "You summarize unread Zulip messages for someone who was away. Use only "
                "the supplied messages and do not invent facts. Be concise and mention "
                "decisions and action items. Reply with JSON only, of the form "
                '{"recap": [{"text": "<one sentence>", "message_ids": [<ids of the '
                "supplied messages that support it>]}, ...]}. Write 3 to 6 sentences. "
                "Every sentence must cite at least one message id from the input; put "
                "the ids only in message_ids, never inside the text.",
                "system",
            ),
            _make_message(f"Messages:\n{context}"),
        ]
    )
    summary_markdown = render_recap_markdown(raw_response, links)

    # The model replies in Markdown, and the web app's `rendered_markdown`
    # helper expects server-rendered HTML, so we run the linkified summary
    # through Zulip's normal Markdown pipeline the same way the existing
    # topic-summary feature does.
    rendered_summary = markdown_convert(
        summary_markdown, message_realm=user_profile.realm
    ).rendered_content

    return {
        "summary": rendered_summary,
        "references": [
            {
                "message_id": message.id,
                "sender": message.sender.full_name,
                "topic": message.topic_name() if message.is_channel_message else "Direct message",
                "link": links[message.id],
            }
            for message in messages
        ],
        "truncated": len(unread_ids) == MAX_RECAP_MESSAGES,
    }


def _topic_cooldown_cache_key(user_profile: UserProfile, stream_id: int, topic_name: str) -> str:
    # Topic names are free-form text, so they are hashed to keep the cache key
    # within memcached's character and length limits.
    topic_hash = hashlib.sha256(topic_name.encode()).hexdigest()[:32]
    return f"topic_drift_check:{user_profile.realm_id}:{stream_id}:{topic_hash}"


def suggest_topic_title(
    user_profile: UserProfile, stream_id: int, topic_name: str
) -> dict[str, Any]:
    no_suggestion: dict[str, Any] = {
        "drifted": False,
        "suggested_title": None,
        "reason": None,
        "message_id": None,
    }

    # Every stream message triggers a drift check from the client, so a shared
    # per-topic cooldown keeps the number of provider calls proportional to
    # active topics rather than to total message volume.
    cache_key = _topic_cooldown_cache_key(user_profile, stream_id, topic_name)
    if cache_get(cache_key) is not None:
        return no_suggestion

    messages = list(
        Message.objects.filter(
            realm=user_profile.realm,
            recipient__type_id=stream_id,
            subject__iexact=topic_name,
            is_channel_message=True,
            usermessage__user_profile=user_profile,
        )
        .select_related("sender", "recipient")
        .order_by("-id")[:MAX_TOPIC_MESSAGES]
    )
    messages.reverse()
    if len(messages) < MIN_TOPIC_MESSAGES:
        return no_suggestion

    # Claim the cooldown before making the call, so that a burst of messages
    # cannot start several concurrent requests for the same topic.  If the
    # provider call fails we release it again, so a transient error does not
    # silence the feature for the whole cooldown window.
    cache_set(cache_key, True, timeout=TOPIC_CHECK_COOLDOWN_SECONDS)

    context = json.dumps([_message_context(message) for message in messages])
    try:
        result = _parse_json_response(
            _complete(
                [
                    _make_message(
                        "You detect topic drift in Zulip conversations. A topic has drifted "
                        "when the recent discussion is consistently about a distinct subject.",
                        "system",
                    ),
                    _make_message(
                        "Analyze this conversation and return JSON only with keys "
                        "drifted (boolean), suggested_title (string or null), and reason (string). "
                        f"Current topic: {topic_name}\nMessages:\n{context}"
                    ),
                ]
            )
        )
    except Exception:
        cache_delete(cache_key)
        raise

    drifted = result.get("drifted") is True
    suggested_title = result.get("suggested_title")
    reason = result.get("reason")
    if not drifted or not isinstance(suggested_title, str) or not suggested_title.strip():
        return {**no_suggestion, "message_id": messages[-1].id}
    return {
        "drifted": True,
        "suggested_title": suggested_title.strip()[:MAX_SUGGESTED_TITLE_LENGTH],
        "reason": (
            reason if isinstance(reason, str) else "The recent discussion has shifted topics."
        ),
        "message_id": messages[-1].id,
    }

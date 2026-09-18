import json
from typing import Any
from unittest import mock

from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion
from typing_extensions import override

from zerver.actions.llm_features import MAX_SUGGESTED_TITLE_LENGTH, _topic_cooldown_cache_key
from zerver.lib.cache import cache_delete
from zerver.lib.test_classes import ZulipTestCase
from zerver.models import UserMessage
from zerver.models.streams import get_stream

AI_SETTINGS = {
    "TOPIC_SUMMARIZATION_MODEL": "test-model",
    "TOPIC_SUMMARIZATION_API_KEY": "test-key",
}


class LLMFeaturesTest(ZulipTestCase):
    @override
    def setUp(self) -> None:
        super().setUp()
        self.user = self.example_user("iago")
        self.login_user(self.user)
        self.channel_name = "Zulip features"
        self.topic_name = "LLM feature work"
        self.subscribe(self.user, self.channel_name)
        sender = self.example_user("hamlet")
        self.message_ids = [
            self.send_stream_message(
                sender,
                self.channel_name,
                content="The recap feature should link back to this message.",
                topic_name=self.topic_name,
            ),
            self.send_stream_message(
                sender,
                self.channel_name,
                content="The title improver should detect sustained drift.",
                topic_name=self.topic_name,
            ),
            self.send_stream_message(
                sender,
                self.channel_name,
                content="We will test both features before submission.",
                topic_name=self.topic_name,
            ),
        ]
        self.stream_id = get_stream(self.channel_name, self.user.realm).id
        # The drift check keeps a per-topic cooldown in memcached, which
        # outlives an individual test, so clear it before each test.
        cache_delete(_topic_cooldown_cache_key(self.user, self.stream_id, self.topic_name))

    def _completion(self, content: str) -> ChatCompletion:
        return ChatCompletion.model_validate(
            {
                "id": "test",
                "object": "chat.completion",
                "created": 1,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": content},
                        "finish_reason": "stop",
                    }
                ],
            }
        )

    def _request_recap(self, model_output: str) -> dict[str, Any]:
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(Completions, "create", return_value=self._completion(model_output)),
        ):
            result = self.client_get("/json/messages/recap")
        self.assert_json_success(result)
        return result.json()["result"]

    def _request_suggestion(self, model_output: str) -> dict[str, Any]:
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(Completions, "create", return_value=self._completion(model_output)),
        ):
            result = self.client_post(
                "/json/topics/improve-title",
                {"stream_id": self.stream_id, "topic_name": self.topic_name},
            )
        self.assert_json_success(result)
        return result.json()["result"]

    def test_recap_requires_login(self) -> None:
        self.logout()
        result = self.client_get("/json/messages/recap")
        self.assert_json_error(result, "Not logged in: API authentication or user session required")

    def test_recap_lists_clickable_references(self) -> None:
        payload = self._request_recap("Three messages describe the implementation plan.")
        self.assertEqual([item["message_id"] for item in payload["references"]], self.message_ids)
        for item in payload["references"]:
            self.assertIn(f"/near/{item['message_id']}", item["link"])
            self.assertIn(f"/topic/{'LLM.20feature.20work'}", item["link"])

    def test_recap_links_structured_citations(self) -> None:
        first, second, third = self.message_ids
        payload = self._request_recap(
            json.dumps(
                {
                    "recap": [
                        {"text": "The recap links back to messages.", "message_ids": [first]},
                        {"text": "Drift detection was discussed.", "message_ids": [second, third]},
                    ]
                }
            )
        )
        summary = payload["summary"]
        # Each cited id becomes an anchor that narrows to that message.
        for message_id in self.message_ids:
            self.assertIn(f"/near/{message_id}", summary)
        self.assertEqual(summary.count("<a "), 3)
        self.assertIn("The recap links back to messages.", summary)

    def test_recap_ignores_structured_citations_to_unknown_messages(self) -> None:
        first = self.message_ids[0]
        payload = self._request_recap(
            json.dumps(
                {
                    "recap": [
                        {"text": "Real and invented citations.", "message_ids": [first, 987654321]},
                    ]
                }
            )
        )
        summary = payload["summary"]
        self.assertIn(f"/near/{first}", summary)
        self.assertNotIn("987654321", summary)
        self.assertEqual(summary.count("<a "), 1)

    def test_recap_falls_back_to_prose_citations(self) -> None:
        # If the model ignores the JSON format, bracketed ids in prose are
        # still turned into links and unknown ids are dropped.
        cited, other = self.message_ids[0], self.message_ids[1]
        payload = self._request_recap(
            f"The recap links back [#{cited}] and drift is discussed [{other}] but not [#987654321]."
        )
        summary = payload["summary"]
        self.assertIn(f"/near/{cited}", summary)
        self.assertIn(f"/near/{other}", summary)
        self.assertNotIn("987654321", summary)
        self.assertEqual(summary.count("<a "), 2)

    def test_recap_with_no_unread_messages_skips_the_provider(self) -> None:
        UserMessage.objects.filter(user_profile=self.user).update(flags=UserMessage.flags.read.mask)
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(Completions, "create") as provider,
        ):
            result = self.client_get("/json/messages/recap")
        self.assert_json_success(result)
        self.assertEqual(result.json()["result"]["references"], [])
        provider.assert_not_called()

    def test_recap_reports_provider_failure(self) -> None:
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(Completions, "create", side_effect=RuntimeError("boom")),
        ):
            result = self.client_get("/json/messages/recap")
        self.assert_json_error(result, "The AI recap is temporarily unavailable.")

    def test_recap_disabled_without_a_configured_model(self) -> None:
        with self.settings(TOPIC_SUMMARIZATION_MODEL=None):
            result = self.client_get("/json/messages/recap")
        self.assert_json_error(result, "AI features are not enabled on this server.")

    def test_topic_title_improver_returns_suggestion(self) -> None:
        payload = self._request_suggestion(
            '{"drifted": true, "suggested_title": "LLM feature validation", '
            '"reason": "The recent messages focus on validation rather than implementation."}'
        )
        self.assertTrue(payload["drifted"])
        self.assertEqual(payload["suggested_title"], "LLM feature validation")
        self.assertEqual(payload["message_id"], self.message_ids[-1])

    def test_topic_title_improver_reports_no_drift(self) -> None:
        payload = self._request_suggestion(
            '{"drifted": false, "suggested_title": null, "reason": "Still on topic."}'
        )
        self.assertFalse(payload["drifted"])
        self.assertIsNone(payload["suggested_title"])

    def test_topic_title_improver_truncates_long_titles(self) -> None:
        payload = self._request_suggestion(
            '{"drifted": true, "suggested_title": "' + "x" * 200 + '", "reason": "r"}'
        )
        assert isinstance(payload["suggested_title"], str)
        self.assertEqual(len(payload["suggested_title"]), MAX_SUGGESTED_TITLE_LENGTH)

    def test_topic_title_improver_cooldown_limits_provider_calls(self) -> None:
        response = self._completion(
            '{"drifted": true, "suggested_title": "LLM feature validation", "reason": "r"}'
        )
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(Completions, "create", return_value=response) as provider,
        ):
            first = self.client_post(
                "/json/topics/improve-title",
                {"stream_id": self.stream_id, "topic_name": self.topic_name},
            )
            second = self.client_post(
                "/json/topics/improve-title",
                {"stream_id": self.stream_id, "topic_name": self.topic_name},
            )
        self.assert_json_success(first)
        self.assert_json_success(second)
        self.assertTrue(first.json()["result"]["drifted"])
        # The second request inside the cooldown window is answered without
        # paying for another provider call.
        self.assertFalse(second.json()["result"]["drifted"])
        self.assertEqual(provider.call_count, 1)

    def test_topic_title_improver_needs_enough_messages(self) -> None:
        quiet_topic = "Barely started"
        self.send_stream_message(
            self.example_user("hamlet"), self.channel_name, content="Hi", topic_name=quiet_topic
        )
        cache_delete(_topic_cooldown_cache_key(self.user, self.stream_id, quiet_topic))
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(Completions, "create") as provider,
        ):
            result = self.client_post(
                "/json/topics/improve-title",
                {"stream_id": self.stream_id, "topic_name": quiet_topic},
            )
        self.assert_json_success(result)
        self.assertFalse(result.json()["result"]["drifted"])
        provider.assert_not_called()

    def test_topic_title_improver_handles_invalid_json(self) -> None:
        with (
            self.settings(**AI_SETTINGS),
            mock.patch.object(
                Completions, "create", return_value=self._completion("not json at all")
            ),
        ):
            result = self.client_post(
                "/json/topics/improve-title",
                {"stream_id": self.stream_id, "topic_name": self.topic_name},
            )
        self.assert_json_error(result, "The topic title suggestion is temporarily unavailable.")

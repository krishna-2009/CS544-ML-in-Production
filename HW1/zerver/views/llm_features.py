import logging

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.utils.translation import gettext as _
from openai import OpenAIError
from pydantic import Json

from zerver.actions.llm_features import generate_unread_recap, suggest_topic_title
from zerver.lib.exceptions import JsonableError
from zerver.lib.response import json_success
from zerver.lib.typed_endpoint import typed_endpoint, typed_endpoint_without_parameters
from zerver.models import UserProfile

logger = logging.getLogger(__name__)

# Anything that can go wrong between us and the model provider: a missing
# key, a timeout, a rate limit, or a reply we could not parse.  All of these
# are turned into a clean API error rather than a 500 for the client.
PROVIDER_ERRORS = (OpenAIError, RuntimeError, ValueError)


def _ensure_ai_enabled() -> None:
    if settings.TOPIC_SUMMARIZATION_MODEL is None:
        raise JsonableError(_("AI features are not enabled on this server."))


@typed_endpoint_without_parameters
def get_unread_message_recap(request: HttpRequest, user_profile: UserProfile) -> HttpResponse:
    _ensure_ai_enabled()
    try:
        recap = generate_unread_recap(user_profile)
    except PROVIDER_ERRORS as error:
        logger.warning("Unread recap failed for user %s: %s", user_profile.id, error)
        raise JsonableError(_("The AI recap is temporarily unavailable.")) from error
    return json_success(request, recap)


@typed_endpoint
def improve_topic_title(
    request: HttpRequest,
    user_profile: UserProfile,
    *,
    stream_id: Json[int],
    topic_name: str,
) -> HttpResponse:
    _ensure_ai_enabled()
    try:
        suggestion = suggest_topic_title(user_profile, stream_id, topic_name)
    except PROVIDER_ERRORS as error:
        logger.warning("Topic title suggestion failed for user %s: %s", user_profile.id, error)
        raise JsonableError(_("The topic title suggestion is temporarily unavailable.")) from error
    return json_success(request, suggestion)

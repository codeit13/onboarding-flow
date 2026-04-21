"""External-world providers.

Each capability the agent needs from the outside world (calendars, mail,
interview agent, Claude scoring) lives behind a small Protocol here. The rest
of the code imports from ``app.providers`` and doesn't care whether the
concrete implementation is the in-memory mock or the real Microsoft Graph /
Claude / Virtual Interview Agent backend.

Swapping to real services at runtime:
    AXIS_CALENDAR_PROVIDER=graph    # default: mock
    AXIS_MESSAGING_PROVIDER=graph   # default: mock
    AXIS_SCORING_PROVIDER=claude    # default: heuristic
    AXIS_INTERVIEW_PROVIDER=live    # default: scripted
    AXIS_ACS_PROVIDER=azure         # default: mock

The factory in this package reads those env vars and returns the right
concrete instance.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .acs_provider import (
    AcsCallSession,
    AcsProvider,
    AzureAcsProvider,
    MockAcsProvider,
)
from .calendar_provider import CalendarProvider, MockCalendarProvider
from .graph_calendar_provider import GraphCalendarProvider
from .messaging_provider import MessagingProvider, MockMessagingProvider
from .graph_messaging_provider import GraphMessagingProvider
from .whatsapp import (
    MetaCloudWhatsAppProvider,
    MockWhatsAppProvider,
    TwilioWhatsAppProvider,
    WhatsAppProvider,
    WhatsAppSendResult,
    WhatsAppWebhookPayload,
)


@lru_cache(maxsize=1)
def get_calendar_provider() -> CalendarProvider:
    choice = os.getenv("AXIS_CALENDAR_PROVIDER", "mock").lower()
    if choice == "graph":
        return GraphCalendarProvider()
    return MockCalendarProvider()


@lru_cache(maxsize=1)
def get_messaging_provider() -> MessagingProvider:
    choice = os.getenv("AXIS_MESSAGING_PROVIDER", "mock").lower()
    if choice == "graph":
        return GraphMessagingProvider()
    return MockMessagingProvider()


@lru_cache(maxsize=1)
def get_acs_provider() -> AcsProvider:
    """Return the ACS Call Automation provider.

    ``AXIS_ACS_PROVIDER=mock`` (default) → offline simulation suitable
    for the demo and tests. ``AXIS_ACS_PROVIDER=azure`` → real Azure
    Communication Services Call Automation (requires connection string,
    base URL, and the SDK installed).
    """
    choice = os.getenv("AXIS_ACS_PROVIDER", "mock").lower()
    if choice == "azure":
        return AzureAcsProvider()
    return MockAcsProvider()


@lru_cache(maxsize=1)
def get_whatsapp_provider() -> WhatsAppProvider:
    """Return the WhatsApp provider.

    ``AXIS_WHATSAPP_PROVIDER=mock`` (default) -> in-memory mock.
    ``AXIS_WHATSAPP_PROVIDER=twilio`` -> Twilio WhatsApp API.
    ``AXIS_WHATSAPP_PROVIDER=meta`` -> Meta Cloud API.
    """
    choice = os.getenv("AXIS_WHATSAPP_PROVIDER", "mock").lower()
    if choice == "twilio":
        return TwilioWhatsAppProvider()
    if choice == "meta":
        return MetaCloudWhatsAppProvider()
    return MockWhatsAppProvider()


def reset_providers() -> None:
    """Test helper — drop the cached singletons and rebuild on next call."""
    get_calendar_provider.cache_clear()
    get_messaging_provider.cache_clear()
    get_acs_provider.cache_clear()
    get_whatsapp_provider.cache_clear()
    # Also reset the mock stores so tests are isolated.
    MockCalendarProvider.reset_global_state()
    MockMessagingProvider.reset_global_state()
    MockAcsProvider.reset_global_state()
    MockWhatsAppProvider.reset_global_state()


__all__ = [
    "AcsCallSession",
    "AcsProvider",
    "AzureAcsProvider",
    "CalendarProvider",
    "GraphCalendarProvider",
    "GraphMessagingProvider",
    "MessagingProvider",
    "MockAcsProvider",
    "MockCalendarProvider",
    "MockMessagingProvider",
    "get_acs_provider",
    "get_calendar_provider",
    "get_messaging_provider",
    "get_whatsapp_provider",
    "MetaCloudWhatsAppProvider",
    "MockWhatsAppProvider",
    "TwilioWhatsAppProvider",
    "WhatsAppProvider",
    "WhatsAppSendResult",
    "WhatsAppWebhookPayload",
    "reset_providers",
]

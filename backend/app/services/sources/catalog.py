"""Catalogue of platforms BeforeYouGo investigated but could NOT integrate here.

Nothing in this file pretends a connector exists. Each entry records what the
research found about the platform's access options and why no connector ships.
Status is refreshed by a real connectivity probe (see sources.service.probe_source).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import SourceStatus


@dataclass(frozen=True)
class PlatformEntry:
    key: str
    name: str
    homepage: str
    access_method: str
    limitations: str
    auth_requirement: str
    rate_limit_note: str
    status: SourceStatus
    why_not_integrated: str
    terms_url: str | None = None
    researched_on: str = "2026-10-11"


PLATFORMS: list[PlatformEntry] = [
    PlatformEntry(
        key="unstop",
        name="Unstop",
        homepage="https://unstop.com",
        access_method="No public or partner API was found in the documentation searched. Third-party scrapers exist, which implies undocumented endpoints.",
        limitations="Automated collection terms were not reviewable from this environment; undocumented endpoints are not a permitted access method.",
        auth_requirement="Unknown: no documented developer programme found.",
        rate_limit_note="Not documented.",
        status=SourceStatus.NOT_IMPLEMENTED,
        why_not_integrated=(
            "No official API. Using undocumented endpoints or scraping without confirmed permission would violate the "
            "integration hierarchy. A partner/API agreement with Unstop (or an organizer-supplied event URL) is needed."
        ),
    ),
    PlatformEntry(
        key="devfolio",
        name="Devfolio",
        homepage="https://devfolio.co",
        access_method="No public hackathon-listing API found. Devfolio's published guides cover organizer and hacker workflows only.",
        limitations="Only individual event pages could be submitted by URL; listing discovery is not available.",
        auth_requirement="Unknown: no documented public developer programme found.",
        rate_limit_note="Not documented.",
        status=SourceStatus.NOT_IMPLEMENTED,
        why_not_integrated="No documented listing API. Organizer-submitted event URLs (schema.org parsing) are the supported route.",
        terms_url="https://guide.devfolio.co/",
    ),
    PlatformEntry(
        key="mlh",
        name="Major League Hacking (MLH)",
        homepage="https://mlh.io",
        access_method="No public events API found. Season event lists are published as web pages.",
        limitations="Page extraction was not verified to be permitted; no feed was found.",
        auth_requirement="Unknown.",
        rate_limit_note="Not documented.",
        status=SourceStatus.NOT_IMPLEMENTED,
        why_not_integrated="No official feed or API; permission for automated page extraction is unconfirmed.",
    ),
    PlatformEntry(
        key="eventbrite",
        name="Eventbrite",
        homepage="https://www.eventbrite.com",
        access_method=(
            "REST API v3. Public event search was withdrawn in 2019-2020. Remaining endpoints fetch a known event by ID or "
            "list events for an organization/venue and require an OAuth token."
        ),
        limitations="Cannot discover public events by keyword or location through the API; only known events/organizations with a token.",
        auth_requirement="OAuth bearer token (credentials not available here).",
        rate_limit_note="Per Eventbrite API terms (not verified here).",
        status=SourceStatus.NEEDS_CREDENTIALS,
        why_not_integrated=(
            "No credentials, and egress to the API host is denied in this environment, so a connector could not be "
            "verified against real responses. A parser written blind would be unverifiable."
        ),
        terms_url="https://www.eventbrite.com/platform/api",
    ),
    PlatformEntry(
        key="meetup",
        name="Meetup",
        homepage="https://www.meetup.com",
        access_method="GraphQL API at api.meetup.com/gql-ext with OAuth2 bearer tokens. Documented limit: 500 points per 60 seconds.",
        limitations="Public cross-group event search is not clearly documented as available to ordinary tokens.",
        auth_requirement="OAuth2 access token (credentials not available here).",
        rate_limit_note="500 query points per 60 seconds (documented).",
        status=SourceStatus.NEEDS_CREDENTIALS,
        why_not_integrated="No credentials and egress denied, so the GraphQL schema and responses could not be verified.",
        terms_url="https://www.meetup.com/api/guide/",
    ),
    PlatformEntry(
        key="hackerearth",
        name="HackerEarth",
        homepage="https://www.hackerearth.com",
        access_method="The documented v4 API covers code compilation/execution only. No challenge or hackathon listing endpoint is documented.",
        limitations="No documented way to list public challenges.",
        auth_requirement="Client secret header (for the code-evaluation API only).",
        rate_limit_note="Quota-based; documented for the code-evaluation API only.",
        status=SourceStatus.NOT_IMPLEMENTED,
        why_not_integrated="The documented API does not expose events. Page extraction permission is unconfirmed.",
        terms_url="https://www.hackerearth.com/docs/wiki/developers/v4/",
    ),
    PlatformEntry(
        key="townscript",
        name="Townscript",
        homepage="https://www.townscript.com",
        access_method="No public listing API documentation was found.",
        limitations="Individual event pages could be submitted by URL if they publish structured data and are reachable.",
        auth_requirement="Unknown.",
        rate_limit_note="Not documented.",
        status=SourceStatus.NOT_IMPLEMENTED,
        why_not_integrated="No documented API; permission for page extraction unconfirmed.",
    ),
]

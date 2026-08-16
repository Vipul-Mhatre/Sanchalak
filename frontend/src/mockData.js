// Mock data for the four product states.
// Set USE_MOCK = false to wire the real backend (/api/chat, /api/reindex).

export const USE_MOCK = true

const SSO_DOC = 'https://docs.flytbase.com/getting-started-with-your-flytbase-account/enterprise-single-sign-on-sso'
const SSO_RELEASE = 'https://releases.flytbase.com/september-2025/enterprise-sso'
const MISSION_SCHED = 'https://docs.flytbase.com/pre-flight-modules/planning/mission-scheduler'
const MISSION_PLAN = 'https://docs.flytbase.com/pre-flight-modules/planning/mission-planning'

export const MOCK_STATES = [
  // ---------------------------------------------------------------
  // 1. NORMAL GROUNDED ANSWER — chips + sources rail, mixed sources
  // ---------------------------------------------------------------
  {
    userText: 'Which accounts requested a feature the platform already supports according to the docs?',
    answer:
      'Looking across the corpus, one open request lines up with a capability the docs already describe:\n\n' +
      '- **Single sign-on for enterprise accounts** [FR-0019] — requested by Meridian AgriTech, Palisade Telecom, Foxglenn Logistics, Amber Ridge Forestry, Duskfield Construction, and Clearwater Mining. The docs page on **Enterprise Single Sign-On (SSO)** [' + SSO_DOC + '] documents SAML 2.0 and SCIM provisioning for enterprise accounts — so these six accounts may be asking for a feature that already exists.\n' +
      '- **Two-factor authentication at the org level** [FR-0032] — requested by Redstone Emergency Response, Elmswood AgriTech, and Blue Harbor Logistics. Not confirmed in the docs.\n' +
      '- **Custom user roles beyond default permission tiers** [FR-0027] — completed; Brightwater Events and Northgate Agriculture were among the requesters.\n\n' +
      'Combined reading: the SSO request [FR-0019·SSO] is the strongest candidate for a feature that is already shipped.',
    citations: [
      {
        id: 'FR-0019',
        type: 'customer_data',
        record_type: 'feature_request',
        content_preview: 'Single sign-on support for enterprise accounts — status: new. Requested by Meridian AgriTech, Palisade Telecom, Foxglenn Logistics, Amber Ridge Forestry, Duskfield Construction, Clearwater Mining.',
      },
      {
        id: 'FR-0032',
        type: 'customer_data',
        record_type: 'feature_request',
        content_preview: 'Two-factor authentication enforcement at the org level — status: new. Requested by Redstone Emergency Response, Elmswood AgriTech, Blue Harbor Logistics, Clearwater Mining, Longview Conservation Trust.',
      },
      {
        id: 'FR-0027',
        type: 'customer_data',
        record_type: 'feature_request',
        content_preview: 'Custom user roles beyond the default permission tiers — status: completed. Requested by Brightwater Events, Northgate Agriculture, Elmswood AgriTech, Moonvale Oil & Gas, Palisade Telecom.',
      },
      {
        id: SSO_DOC,
        type: 'docs',
        url: SSO_DOC,
        title: 'Enterprise Single Sign-On (SSO)',
        source_site: 'docs',
        content_preview: 'FlytBase supports Enterprise SSO via SAML 2.0 identity providers, with SCIM user provisioning for enterprise accounts. Configure your IdP connection from the organization settings page.',
      },
      {
        id: 'FR-0019·SSO',
        type: 'both',
        record_type: 'feature_request',
        content_preview: 'Claim grounded in both sources: FR-0019 requests SSO for enterprise accounts; the docs confirm Enterprise SSO is already available. The request may predate the shipped capability.',
      },
    ],
    contradictions: [],
  },

  // ---------------------------------------------------------------
  // 2. REFUSAL — insufficient grounding, calm and matter-of-fact
  // ---------------------------------------------------------------
  {
    userText: 'What is the weather on Mars?',
    answer: 'I don\'t have enough information to answer this question.',
    refused: true,
    related: [
      {
        id: 'MTG-0003',
        preview: 'Site readiness and network reliability discussion for Northfall Security Group',
      },
      {
        id: 'ISS-0042',
        preview: 'Existing API key stopped authenticating after a routine credential rotation',
      },
    ],
    citations: [],
    contradictions: [],
  },

  // ---------------------------------------------------------------
  // 3. STALE / CACHED FALLBACK — dot + "cached" next to the chip
  // ---------------------------------------------------------------
  {
    userText: 'How does mission scheduling work in FlytBase?',
    answer:
      'Mission Scheduler lets you queue flights for later execution: pick a mission, set a start time, and the dock runs it automatically when the time arrives [' + MISSION_SCHED + '].\n\n' +
      'For a single flight, the Path Mission flow covers waypoint planning [' + MISSION_PLAN + '].\n\n' +
      'One page was served from a cached copy because the live fetch failed.',
    citations: [
      {
        id: MISSION_SCHED,
        type: 'docs',
        url: MISSION_SCHED,
        title: 'Mission Scheduler',
        source_site: 'docs',
        stale: true,
        content_preview: 'Queue flights to run at a scheduled time. Configure the start time and recurrence, then the dock executes the mission without operator intervention.',
      },
      {
        id: MISSION_PLAN,
        type: 'docs',
        url: MISSION_PLAN,
        title: 'Mission Planning',
        source_site: 'docs',
        stale: false,
        content_preview: 'Plan a mission by placing waypoints on the map, configuring altitude and speed, and reviewing the expected flight path before upload.',
      },
    ],
    contradictions: [],
  },

  // ---------------------------------------------------------------
  // 4. CONTRADICTION FLAG — banner above the relevant part
  // ---------------------------------------------------------------
  {
    userText: 'Do any customers want features we already shipped?',
    answer:
      'Yes — one strong match. **Single sign-on for enterprise accounts** [FR-0019] is still marked *new* and requested by six accounts, yet the platform already ships **Enterprise SSO** [' + SSO_RELEASE + '] per the September 2025 release notes.',
    citations: [
      {
        id: 'FR-0019',
        type: 'customer_data',
        record_type: 'feature_request',
        content_preview: 'Single sign-on support for enterprise accounts — status: new. Requested by Meridian AgriTech, Palisade Telecom, Foxglenn Logistics, Amber Ridge Forestry, Duskfield Construction, Clearwater Mining.',
      },
      {
        id: SSO_RELEASE,
        type: 'docs',
        url: SSO_RELEASE,
        title: 'Enterprise SSO',
        source_site: 'releases',
        content_preview: 'September 2025 release: Enterprise SSO is now available for enterprise accounts, including SAML 2.0 and automated user provisioning.',
      },
    ],
    contradictions: [
      {
        analysis: 'FR-0019 "Single sign-on support for enterprise accounts" is status "new", but Enterprise SSO shipped in the September 2025 release (releases.flytbase.com/september-2025/enterprise-sso). The six requesting accounts may not know the capability already exists.',
      },
    ],
  },
]

export const MOCK_REINDEX_SEED = [
  { time: '14:02:11', msg: 'full-build: 51 accounts · 56 feature requests · 721 issues · 412 tasks · 214 meeting notes (8.4s)' },
  { time: '14:05:47', msg: 'delta-reindex: accounts.md changed → 3 records re-embedded (86ms)' },
  { time: '14:08:03', msg: 'delta-reindex: no changes detected — index up to date' },
]

let reindexFlip = false
export function mockReindexEvent() {
  reindexFlip = !reindexFlip
  const now = new Date().toLocaleTimeString('en-GB', { hour12: false })
  if (reindexFlip) {
    return { time: now, msg: 'delta-reindex: issues.md changed → 4 records re-embedded · 1 removed (92ms)' }
  }
  return { time: now, msg: 'delta-reindex: no changes detected — index up to date' }
}

# 23 — Responsive internal web application and PWA

## Decision

Build SpotZⁱ as a responsive internal web application and package the same interface as an installable Progressive Web App. Investigators use one centrally maintained system in a browser or a desktop-like standalone window. No separate Windows or macOS codebase is required.

## PWA scope

The web manifest defines the SpotZⁱ name, icon, theme colors, start URL, and standalone display mode. A service worker caches only versioned application-shell assets: HTML entry point, CSS, JavaScript, icons, and an offline status page.

Case data, evidence, model output, audit records, and human decisions remain server-authoritative. Do not persist whole claim rows, case briefs, member details, authentication tokens, or decision forms in the service-worker cache.

## Online and offline behavior

| Capability | Online | Offline/interrupted connection |
|---|---|---|
| Open installed application | Current shell | Cached shell with offline banner |
| View previously loaded navigation shell | Yes | Yes |
| Load or refresh case evidence | Yes | Unavailable; never substitute stale data silently |
| Reveal synthetic evidence | Server-authorized | Disabled |
| Record or approve a decision | Server transaction | Disabled; no queued approval |
| Export a brief | Authorized server export | Disabled unless already downloaded by the user |
| Receive notifications | Optional internal notification | No sensitive content in notification body |

When offline, the UI must show dataset/run/time and a prominent read-only state. It must never imply that cached values are current. Do not queue final decisions for later background submission because the evidence or case version may change before reconnection.

## Responsive layouts

- Desktop ≥1280px: full sidebar, dense queue, multi-column case workspace.
- Compact desktop/tablet 768–1279px: collapsed navigation, horizontally scrollable evidence tables, two-column case summary.
- Small viewport <768px: single-column triage view with limited graph interaction. Final approval screens should still display evidence version, limitations, and rationale fields before submission.

The primary target remains payer-managed desktops and tablets. Small-phone support is for urgent read-only triage rather than long investigations.

## Notifications

Optional notifications may announce: assignment received, requested evidence available, approval returned, or analysis run completed. Notification text should use case IDs and neutral wording, without provider/member names, medical detail, risk scores, or outcomes. Opening a notification requires normal authentication and authorization.

Users explicitly opt in. Notification permission is never requested on first page load; request it from a clear user action inside preferences.

## Update lifecycle

Use a versioned cache name. Install the new worker in the background, display “Update available,” and activate it after the user chooses to refresh or reaches a safe navigation point. A forced reload must not interrupt an unsaved human rationale.

The API exposes its compatible frontend contract version. If an installed shell is incompatible, block workflow actions and require refresh rather than sending malformed decisions.

## Security and operations

- Serve over HTTPS outside localhost.
- Apply normal server sessions, RBAC, CSRF protection, and tenant isolation.
- Set a restrictive Content Security Policy and avoid third-party runtime scripts.
- Do not store bearer tokens in local storage.
- Clear application caches on logout where practical; cached shell assets contain no case data.
- Treat installability as presentation, not an authentication boundary.
- Test service-worker updates, offline state, logout, shared-device behavior, and stale-case conflicts.

## Acceptance criteria

- Supported browsers offer an installable SpotZⁱ experience with correct name, icon, and standalone launch.
- Core navigation works at desktop and compact widths.
- Application shell loads during a simulated outage and clearly indicates offline/read-only status.
- `/api/` responses are never written to the service-worker cache.
- Evidence reveals and decision submissions fail closed while offline.
- A returning online user must refresh stale case data before a decision.
- An application update cannot discard an unsaved rationale.

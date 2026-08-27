# Identity and Workspace Authorization Contract

## Boundary decision

PulseIQ does not implement passwords, password reset, JWT signing, or refresh-token storage. A managed OIDC provider authenticates the actor; a provider adapter must exchange the authorization code and cryptographically verify the provider response. The framework-neutral orchestration seam now owns one-time callback state, nonce, PKCE, replay consumption, verified-claim revalidation, internal subject mapping, short-lived server-session creation, and authentication-event evidence. PulseIQ remains authoritative for organization/workspace membership, role, permission, revocation, and audit evidence.

This follows proposed ADR-007 while keeping the provider replaceable. The current package includes domain scaffolding, deterministic OIDC/web adapters, and a locally verified PostgreSQL/RLS adapter. It is not a deployed authentication system and does not contain a real provider client/JWKS verifier.

## Trust flow

```text
managed OIDC + MFA
  -> server creates one-time state + nonce + PKCE S256 transaction
  -> provider adapter exchanges the code and verifies signature, issuer, audience, nonce and time
  -> orchestration revalidates claims, consumes replay state and resolves a pre-provisioned subject link
  -> server atomically creates the short-lived session + PII-free authentication event
  -> secure-cookie adapter creates AuthenticatedActor evidence (actor, session, expiry, AMR)
  -> API loads the current server-side session and target resource ownership
  -> API constructs a server-resolved ResourceScope
  -> AuthorizationService loads current exact organization/workspace membership
  -> authoritative session + MFA policy + explicit role permission are evaluated
  -> allow, or a stable non-sensitive denial code
```

Never authorize from a workspace header, URL alone, browser state, OIDC group/role claim, or role supplied by the caller. A future API adapter must resolve the target's `organization_id` and `workspace_id` from trusted persistence before it creates `ResourceScope`. PostgreSQL RLS must independently enforce the same ownership coordinates.

## Canonical roles and exact default permissions

| Role | Permissions |
|---|---|
| Admin | workspace view/manage; membership view/manage; audit view |
| Data Steward | workspace view; dataset view/upload/manage; quality override |
| Analyst | workspace view; dataset view; portfolio analysis; model train; report view/generate; assistant query |
| Risk Reviewer | workspace view; dataset view; portfolio analysis; risk review; report view/generate; assistant query |
| Approver | workspace view; dataset view; model approve; decision approve; report view/deliver; audit view |
| Auditor | workspace view; report view; audit view |
| Read Only | workspace view; report view |

Important separations:

- Admin does not receive raw dataset, portfolio, model, decision, or report-delivery access merely because it can administer membership.
- Analyst can train but cannot approve a model or final decision.
- Approver can approve but cannot train.
- Auditor cannot mutate workspace state.
- Read Only cannot query raw datasets or the assistant.

The default policy requires MFA for every mutation-capable role: Admin, Data Steward, Analyst, Risk Reviewer, and Approver. Organization policy may tighten this; a production adapter must not weaken a legally or contractually required assurance level.

## Membership invariants

- One actor has at most one active membership in one organization/workspace.
- Membership lookup must match actor, organization, workspace, and active status exactly.
- Revocation takes effect on the next authorization check; no role is cached in the authorization request.
- A role change increments the membership revision and replaces the prior role.
- The last active Admin cannot be demoted or revoked.
- Cross-workspace membership targets resolve as a generic `membership_not_found` command failure.
- No-op changes are rejected rather than generating misleading audit evidence.
- Persistence adapters use optimistic revision checks and must commit the membership mutation and audit event atomically.

## Invitation invariants

- Only an actor with `membership.manage` in the exact workspace can issue an invitation.
- Invitation lifetime is bounded to 15 minutes through 7 days.
- The recipient email is normalized and persisted only as an HMAC-SHA-256 binding under a secret key; raw email is not stored in invitation state or audit evidence.
- The bearer token is generated with at least 32 characters of cryptographic randomness by the production factory, returned once, and persisted only as a SHA-256 digest.
- Acceptance requires a currently active authoritative server session, the provider-verified recipient email, and MFA when the invited role requires it.
- Acceptance atomically consumes the pending invitation, creates one active membership, increments the invitation revision, and appends audit evidence. A replay returns the same generic unavailable failure as an unknown or already-used token.
- Wrong-recipient attempts do not consume the invitation. Expired invitations cannot be accepted and do not block a new invitation for the same recipient/workspace.

The provider adapter is responsible for proving that `verified_email` came from a verified provider claim. Caller-supplied browser text is never sufficient.

## Session invariants

- `AuthenticatedActor` timestamps alone do not authorize a request. `AuthorizationService` also requires a matching actor/session pair in the authoritative server-side registry.
- Missing, expired, revoked, or actor-mismatched registry entries all fail closed as `session_inactive` before membership lookup.
- Logout uses optimistic revision checks to revoke the current session and append audit evidence atomically. Revocation takes effect on the next authorization check even if the browser credential has not expired.
- Revocation replay is rejected and cannot create duplicate evidence.
- The web seam now issues and rotates HMAC-authenticated `__Host-pulseiq_session` tickets with `Secure`, `HttpOnly`, `SameSite=Strict`, bounded `Max-Age`, key IDs, and a 30-minute maximum lifetime. A `BrowserRequestAuthenticator` validates the ticket and then requires the exact actor/session pair in the authoritative server registry.
- Mutations require an exact configured origin, same-origin Fetch Metadata when supplied, and a session-bound CSRF synchronizer token delivered outside the HttpOnly cookie. Lookalike origins, duplicate cookies, malformed/tampered tickets, weak/reused keys, unknown key IDs, missing registry rows, expiry, and revocation fail closed with stable non-sensitive codes.
- Key rotation accepts explicitly configured prior verification keys while issuing only with the active key. Logout still revokes the authoritative session first and returns a host-only cookie expiration header. OIDC verification, API middleware composition, global/provider logout, and anomaly-driven revocation remain adapter/deployment work.

## OIDC login invariants

- Login start persists only a SHA-256 state digest; the raw state is returned once in the authorization redirect. Nonce and PKCE verifier remain hidden server-side and are excluded from object representations.
- Authorization uses code flow plus PKCE S256. Transactions expire after 5–15 minutes and transition once from pending to consumed or failed; unknown, expired, failed, and replayed state return the same generic response.
- The provider adapter port must perform token exchange and cryptographic JWT/JWKS validation. Orchestration independently requires the exact configured issuer, client audience, constant-time nonce equality, current token/authentication time, and MFA when policy requires it.
- Provider subjects never self-provision. Exact issuer/subject links resolve to internal UUID actors; absent or invalid mappings fail closed.
- Successful callback atomically consumes the transaction, creates the authoritative session, and appends a PII-free authentication event. Failed verification consumes the transaction and records only a safe reason code—never code, token, nonce, verifier, email, IP, or provider claims.
- Session expiry is the earlier of the 30-minute local limit and the verified identity-token expiry. Authorization still checks the current server registry and workspace membership on every request.

## Audit evidence

Role changes, membership revocations, invitation issuance/acceptance, and session revocation return an immutable event containing event/time, organization/workspace, actor, action, target, request ID, required reason, and SHA-256 hashes of the governed before/after state. Invitation acceptance hashes both consumed-invitation and activated-membership state. Events deliberately exclude names, email addresses, IP addresses, raw identity tokens, bearer invitation tokens, and authentication secrets.

The PostgreSQL migration now provides append-only triggers, a per-workspace SHA-256 event chain, restricted application access, and atomic outbox creation. SEC-003 remains open until the database is deployed with durable retention, external signed checkpoints/export, independent chain verification, outbox processing, alerting, backup/restore evidence, and privileged-access controls.

## Public seams and verification

- `AuthorizationService.authorize(AuthorizationRequest) -> AuthorizationDecision`
- `IdentityAdministrationService.change_role(ChangeMembershipRole) -> MembershipChangeResult`
- `IdentityAdministrationService.revoke(RevokeMembership) -> MembershipChangeResult`
- `IdentityInvitationService.issue(InviteWorkspaceMember) -> InvitationIssueResult`
- `IdentityInvitationService.accept(AcceptWorkspaceInvitation) -> InvitationAcceptanceResult`
- `SessionAdministrationService.logout(RevokeSession) -> SessionRevocationResult`
- Membership, invitation, and session reader/repository ports for provider/database adapters
- `PostgresIdentityRepository` with request-scoped `DatabaseScope` for those ports

Tests cover the exact role matrix, cross-workspace denial, authoritative session expiry/revocation/mismatch, MFA, duplicate membership rejection, immediate role changes and revocations, training/approval separation, cross-workspace target hiding, unchanged-role rejection, unauthorized revocation, last-admin protection, bounded and deduplicated invitation issuance, HMAC email binding, expiry/reissue, verified-recipient acceptance, wrong-recipient non-consumption, atomic membership activation, and replay resistance.

## Remaining production work

1. managed OIDC provider adapter for code exchange/JWKS signature validation, API middleware composition with the implemented OIDC and secure-cookie/CSRF services, provider logout, global revocation, and production assurance mapping;
2. invitation delivery adapter, resend/revoke administration, enumeration/rate-limit controls, and provider-subject binding policy;
3. organization/workspace creation and policy lifecycle;
4. deploy and operate the PostgreSQL migration with non-bypass roles, TLS/secrets, backups/PITR, restore drills, migration controls, and production-cardinality plans;
5. membership/session-change propagation SLO across caches, jobs, workers, signed URLs, and WebSockets;
6. external audit-chain verification/checkpoints, outbox processing, retention, export, and alerting;
7. suspicious-login detection, access review, break-glass, service identities, and enterprise provisioning;
8. privacy/legal acceptance and a selected launch identity provider/region.

# ADR 0011: Team members, power seats and invitation links

Date: 16 Nov 2026 · Status: accepted · Step 41

## Context

Until Step 41, people existed only in `seed_demo.py`. A customer buys Orrfin as one workspace: the
procurement or finance lead signs, then brings in the team. We looked at how Zip, Precoro,
Procurify, Spendflo, Coupa and Ramp do this (public pages, Nov 2026):

- The buyer is an admin; pricing is a platform fee plus paid seats for people with power
  (approve, see everything, configure). People who only raise requests are free and unlimited
  (Precoro "power users", Procurify "Pro" users; Zip is quoted as company-wide).
- People are added by email invite, CSV, or SSO/SCIM; leavers are deactivated, never deleted.
- Admins expect a seat meter, resend/revoke on invites, and a list of what each role can do.

## Decision

1. **Five roles stay** (`requester`, `buyer`, `approver`, `finance`, `admin`). No custom roles yet:
   every role list in the backend is a §9 control, and custom roles would need a review of each.
2. **Power seats.** Buyer, approver, finance and admin each use one seat of
   `orgs.power_seat_limit` (default 10, plan name `Growth`). Requesters are free. A pending
   invitation holds its seat until used, revoked or expired. This is simulated: no billing exists.
3. **Invitations are their own table** (`team_invites`), not half-made `users` rows. The login row
   is created only when the link is used, so a pending invite can never sign in. Same pattern as
   supplier invites: random token, only its SHA-256 stored, single use, 7 days (§9).
   The table is outside row-level security (the token is looked up before any org is known);
   services filter by `org_id`.
4. **Admin-only, with lock-out guards.** Nobody changes their own role or approval limit; the last
   active admin can't be demoted or deactivated. Deactivation deletes every session at once and
   keeps the person's history.
5. **Email is a log line locally.** The admin copies each link; nothing is sent to a real inbox.

## Consequences

- New: `backend/app/modules/team/`, migration `d6a0e2f8b4c1`, `/settings/team`, `/join`, `/settings`.
- `users` gains `department`, `invited_by_id`, `last_seen_at` (written at most every 5 minutes).
- §5 of BUILD_PLAN should list `team_invites` and the new columns; that section needs the
  founder's approval to edit, so it is proposed, not changed.
- Later: CSV import, SSO/SCIM provisioning, custom roles, reassigning a leaver's open work.

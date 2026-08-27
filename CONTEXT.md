# PulseIQ Decision Workspace

PulseIQ is a governed decision workspace for organizations that review business and lending portfolios. This glossary separates people, tenant boundaries, operational work areas, and customer portfolio records.

## Identity and tenancy

**Actor**:
A human or service identity that performs an action in PulseIQ.
_Avoid_: User account, customer

**Organization**:
The tenant and accountable business boundary that subscribes to PulseIQ.
_Avoid_: Account, company workspace

**Workspace**:
An operational area owned by exactly one organization and isolated from every other workspace.
_Avoid_: Tenant, project account

**Membership**:
An actor's current relationship to one workspace, including its role and lifecycle state.
_Avoid_: Login, access token

**Role**:
A named least-privilege responsibility assigned through a membership.
_Avoid_: Permission set, job title

**Permission**:
A single governed action that a role may perform within one workspace.
_Avoid_: Scope, capability

## Portfolio domain

**Portfolio customer**:
A person or business represented in an organization's governed dataset, distinct from a PulseIQ actor.
_Avoid_: User, member

**Dataset version**:
An immutable, traceable snapshot of a governed dataset within one workspace.
_Avoid_: Upload, latest data

**Dataset**:
A logical governed collection within one workspace whose immutable snapshots are Dataset versions.
_Avoid_: File, spreadsheet

**Import job**:
A durable, idempotent unit of background work that references a Dataset version and never carries the file bytes.
_Avoid_: Upload, thread, task

**Schema mapping version**:
An immutable, steward-confirmed interpretation of physical Dataset-version columns as governed concepts, data types, units, currency, direction, and time semantics.
_Avoid_: Column rename, automatic mapping

**Mapping template**:
A versioned reusable Schema mapping version lineage for a recognized source schema; reuse always creates a new confirmation bound to the target Dataset version.
_Avoid_: Global mapping, silent default

**Validation run**:
A reproducible evaluation of one Dataset version under one Schema mapping version and one versioned validation policy.
_Avoid_: Data quality score, check

**Quality warning override**:
An expiring, reason-required, audited acknowledgement of one policy-approved warning in a Validation run; it never changes the original issue or permits a blocking issue to pass.
_Avoid_: Ignore, delete warning, fix data

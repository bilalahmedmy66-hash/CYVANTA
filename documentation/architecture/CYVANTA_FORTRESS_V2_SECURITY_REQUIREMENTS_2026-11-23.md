# CYVANTA FORTRESS V2
## Security Requirements and Architecture Specification

Document ID: CYV-FORTRESS-V2-SRS-001
Version: 2.0.0
Date: 2026-11-23
Status: Architecture Baseline Candidate
Classification: Internal

## 1. Purpose

Define the security and architecture requirements for CYVANTA FORTRESS V2.

V1 remains frozen and preserved. This document does not authorize production implementation or modification of existing execution workflows.

## 2. Architectural Principles

- Least privilege.
- Runtime-enforced tenant isolation.
- Authenticated authorization and approval.
- Separation of duties.
- Fail-closed behavior.
- Evidence integrity and traceability.
- Human accountability.
- Advisory-only AI.
- Explicit change control.

## 3. Existing Baseline

The existing platform includes FastAPI, SQLAlchemy, SQLite, React, Vite, JWT authentication, organization memberships, platform operators, emergency-stop mechanisms, AI analysis services, and FORTRESS V1.

FORTRESS V1 contains 10 logical security layers, 100 registered controls, and 10 logical vault mappings.

Logical vault mappings do not establish physical encryption or independently verified runtime isolation.

V1 must remain independently testable and unchanged.

## 4. Identity and Authorization

V2 must provide:

- User lifecycle management.
- Organization membership lifecycle management.
- Membership revocation enforcement.
- Explicit role-based permissions.
- Authenticated reviewer and approver identities.
- Separation of duties for sensitive approvals.
- Independently governed platform operator permissions.
- Auditable administrative actions.

A valid JWT alone must not preserve authorization after membership revocation.

## 5. Tenant Isolation

All organization-owned resources must be scoped to the authenticated organization membership.

Tenant isolation must be enforced across:

- API endpoints.
- Database queries.
- Background jobs.
- Evidence storage.
- AI processing.
- Audit records.
- Findings and approvals.

Cross-organization access must fail closed.

## 6. Evidence Governance

Evidence must have:

- Organization ownership.
- Classification.
- Provenance.
- Authenticated submission identity.
- Integrity verification.
- Access history.
- Version history.
- Retention policy.
- Controlled deletion.

Classification levels:

1. Public.
2. Internal.
3. Confidential.
4. Restricted.

Storage encryption, backup protection, integrity verification, and deletion requirements must be separately designed and tested.

## 7. AI Data-Handling Modes

### Mode A — Restricted

Default mode.

- Evidence remains inside the approved CYVANTA processing boundary.
- No external AI provider receives evidence.
- External AI credentials must not be used for restricted requests.
- No automatic provider fallback is permitted.
- If internal processing is unavailable, report that analysis is unavailable.

### Mode B — Approved External Analysis

External transmission is allowed only when:

- Organization policy enables it.
- Evidence classification permits it.
- User authorization is valid.
- Required organizational consent exists.
- Redaction and sensitive-data screening complete.
- Provider configuration is approved.
- The transmission decision is auditable.

Gemini is the initially proposed provider.

A valid API key does not constitute authorization to transmit evidence.

### Shared AI Requirements

- Treat evidence as untrusted input.
- Resist prompt injection.
- Validate structured model output.
- Preserve evidence provenance.
- Enforce human review.
- Keep AI advisory-only.
- Never permit AI to authorize or execute security operations.

## 8. Background Worker Security

V2 must provide:

- Job ownership and atomic claiming.
- Worker identity.
- Lease expiration and renewal.
- Safe interrupted-job recovery.
- Duplicate-processing prevention.
- Bounded retries.
- Current authorization validation.
- Organization-policy validation.
- AI mode validation before external transmission.

A queued job must not retain external transmission authorization after the applicable approval has been revoked.

## 9. Findings and Remediation Governance

The findings lifecycle must support:

- Open.
- Under Review.
- Confirmed.
- Assigned.
- Remediation Proposed.
- Awaiting Approval.
- Remediation In Progress.
- Resolved.
- Closed.
- Reopened.

AI may recommend remediation but may not execute it.

Sensitive changes require separately authorized human approval.

## 10. Audit and Retention

Audit records must capture:

- Authentication events.
- Membership and permission changes.
- Evidence submission and access.
- Review and approval actions.
- Policy decisions.
- AI mode selection.
- External transmission authorization.
- Worker outcomes.
- Finding lifecycle changes.
- Administrative actions.

Retention policies must separately cover original evidence, redacted evidence, AI results, audit events, findings, and backups.

Deletion, legal holds, backup expiry, and derived-data handling must be explicitly defined.

## 11. Security Testing

Mandatory test areas:

1. Authentication and session security.
2. Tenant isolation.
3. Membership revocation.
4. Role and permission enforcement.
5. Approval identity and separation of duties.
6. Evidence integrity.
7. Evidence classification.
8. Restricted-mode external-transmission prevention.
9. External-mode authorization.
10. Redaction effectiveness.
11. Prompt-injection resistance.
12. Worker concurrency and recovery.
13. Retention and deletion.
14. Audit integrity.
15. V1 regression.

Critical acceptance conditions:

- Restricted mode produces zero external provider calls.
- External analysis fails closed without authorization.
- Disallowed evidence never reaches an external provider.
- Revoked membership prevents unauthorized processing.
- Provider errors do not disclose sensitive information.
- AI cannot trigger execution or remediation.

## 12. Implementation Sequence

Phase 0: Architecture and requirements approval.

Phase 1: Identity and authorization foundations.

Phase 2: Evidence governance and storage.

Phase 3: Worker reliability and processing authorization.

Phase 4: Restricted and approved external AI modes.

Phase 5: Findings and remediation governance.

Phase 6: AI Intelligence Workspace.

Phase 7: Dashboards, reporting, and reliability improvements.

Each phase requires a separate design review, implementation authorization, backup, regression testing, security review, and closure report.

## 13. Change-Control Restrictions

The following require separate explicit approval:

- Database schema changes.
- ORM changes.
- Migrations.
- Authentication changes.
- Existing execution workflow changes.
- Emergency-stop changes.
- External provider integration changes.
- Physical evidence storage changes.

No implementation is authorized solely by this specification.

## 14. Definition of Done

V2 is not complete until runtime tenant isolation, authenticated authorization, evidence governance, both AI modes, worker reliability, retention, deletion, auditability, and V1 regression have been verified.

Automated test success alone is not independent security certification.

## 15. Approval Record

Document status: Architecture Baseline Candidate.

Approved direction:
- Preserve V1.
- Develop V2 as a controlled extension.
- Include both AI modes.
- Make Restricted mode the default.
- Maintain human authorization and advisory-only AI.

Implementation authorization: Not granted.

Production deployment authorization: Not granted.

Final architecture approval: Approved.
Approval recorded: 2026-11-23, explicit project-owner confirmation.

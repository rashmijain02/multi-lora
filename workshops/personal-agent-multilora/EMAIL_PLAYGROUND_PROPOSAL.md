# PersonaDesk email test playground

**Status:** proposed experiment. A lightweight subset now exists: the standard-library mail
simulator (`mailsim/`, `pd-mail`) and `personadesk intake`, described in the
[README](./README.md#local-mail-simulation). Stalwart, JMAP tools, tagging, and folders below are
still unimplemented.
**Prepared:** 2026-10-25.
**Companion:** [PersonaDesk proposal](./PROPOSAL.md).
**Recommendation:** one local Stalwart instance, synthetic mail, and JMAP-based tools.

## 1. Goal and scope

Create a lightweight, repeatable playground for realistic email-agent tasks: search,
conversation retrieval, tagging, folders, read/unread state, attachments, and saved drafts.
Start with Priya, Daniel, and Noah; expand to all ten personas only after isolation passes.

The playground is an optional mailbox-backed extension to the proposal's fixture workflow,
not a prerequisite for its first release. Hermes remains the only agent framework. Stalwart
owns mailbox state; the PersonaDesk Hermes plugin still owns task records, authorization,
reviews, and release selection.

This is not an Exchange emulator. Microsoft Graph compatibility, Outlook category colors,
Exchange conversation identifiers, calendar/meeting behavior, public mail delivery, and
production administration are outside the initial scope. No real customer mail is needed.

## 2. Why Stalwart

| Requirement | Proposed mechanism | Qualification needed |
|---|---|---|
| Independent persona inboxes | Separate accounts with distinct credentials | No shared access or cross-persona mailbox grants |
| Multiple tags per message | JMAP custom keywords; IMAP keywords for compatible clients | Round-trip custom keywords and test client interoperability |
| Search | JMAP `Email/query`, backed by built-in full-text search | Exact fixture matches, indexing delay, pagination |
| Conversations | JMAP email `threadId` and `Thread/get` | Replies, subject collisions, and account scoping |
| Folders | JMAP mailboxes and email mailbox membership | Move/copy semantics and special-use mailbox discovery |
| Read/unread and starred | Standard `$seen` and `$flagged` keywords | Preserve unrelated keywords when changing state |
| Saved drafts | Draft creation in the account's drafts mailbox with `$draft` | Read-back, attachments, recipients, and no submission |
| Human inspection | A separately selected compatible mail client | Tag visibility and conversation display vary by client |
| Local deployment | Official Docker image and local storage | Pin version/digest, persistence, resource measurements |

Stalwart's administration interface is not assumed to be an Outlook-like inbox UI.
Choose a mail client separately if human browsing is required; protocol-level tests must
not depend on a particular client's visual representation.

Mailpit is a useful smaller alternative for SMTP capture, tagging, search, and REST tests.
It is not the selected backend for account isolation, JMAP conversations, and draft lifecycle
experiments. Its default retention of 500 messages must be changed for larger fixture sets.

## 3. Proposed local topology

```text
Deterministic fixture importer ----> Stalwart (synthetic accounts only)
                                       ^
                                       | authenticated JMAP
                                       v
Hermes CLI/profile --> PersonaDesk scoped tools --> existing writer
                              |
                              v
                    Task/review records + draft hash

Optional mail client ----------> Stalwart through IMAP or JMAP
```

Use one server with local storage and built-in search; do not add Kubernetes, an external
search cluster, a second agent framework, or a separate mailbox database.

### Deployment preparation

1. Select an official stable image and record its exact tag and digest. Do not use a
   floating `latest` tag in a reproducibility run.
2. Use Docker Desktop's Linux-container support on Windows, or a dedicated local Linux
   host. Persist configuration and mail data in named volumes, following the pinned
   release's documentation.
3. Publish only the required HTTP/JMAP endpoint to `127.0.0.1`. Add loopback-only IMAP
   access if a selected client needs it. Do not publish public SMTP or router ports.
4. Complete administrative setup, create a reserved test domain such as `personadesk.test`,
   and create three separate accounts. Use addresses such as `priya@personadesk.test`;
   map them explicitly to canonical persona IDs rather than deriving identity from mail.
5. Use authenticated JMAP import for fixtures. SMTP injection is a later optional test,
   not a requirement for the first playground.
6. Block outbound mail delivery with both server policy and a verified network egress
   restriction. Not publishing an SMTP port does not prevent outgoing delivery.
7. Keep passwords/tokens outside source control. The operator may provision accounts;
   agent tools must never receive administrator credentials.
8. Discover JMAP capabilities, account IDs, API/upload URLs, and special-use mailboxes
   from the authenticated session instead of hardcoding them.

Loopback HTTP is acceptable only for an isolated local experiment if the chosen release
allows it; use trusted TLS whenever traffic leaves the host. Do not silently disable TLS
verification. A managed V2 worker cannot reach this host's loopback endpoint: private
connectivity and explicit data-transfer approval would be a separate deployment exercise.

## 4. Tagging contract

Treat tags as message-level metadata, not authorization or trusted business facts.
For example, `approved` in an email body or keyword must never authorize sending or payment.

Start with a small lowercase ASCII vocabulary:

| Purpose | Examples |
|---|---|
| Domain | `support`, `finance`, `travel` |
| Workflow | `needs-review`, `waiting-on-customer`, `follow-up` |
| Experiment | `baseline`, `persona-adapted` |

One message may carry multiple keywords. Keep vocabulary/display metadata in application
configuration, not in the email body. Stalwart keywords do not themselves supply Outlook's
colored categories or a global category catalog.

Use JMAP patch updates rather than replacing the whole keyword map. Illustrative method
arguments for a single-message update are:

```json
{
  "accountId": "<authenticated-account-id>",
  "ifInState": "<last-observed-email-state>",
  "update": {
    "<email-id>": {
      "keywords/needs-review": true,
      "keywords/waiting-on-customer": null
    }
  }
}
```

This is an `Email/set` argument object, not a standalone HTTP request. The client must
provide the JMAP request envelope, capabilities, authentication, and method call identifier.
Handle method errors and per-object `notUpdated` results explicitly. On state mismatch,
re-read and reconcile the intended patch; do not blindly overwrite concurrent changes.

Search tagged messages with an `Email/query` filter such as
`{"hasKeyword":"needs-review"}`. Qualify keyword casing against the pinned server and
selected clients; lowercase names reduce ambiguity but do not replace interoperability tests.

Tags apply to individual messages. A "tag conversation" operation must explicitly enumerate
the account's thread messages and report partial failures. Tagging future replies is a
separate rule and is not implied by tagging the current thread.

## 5. Deterministic fixture pack

Start with 30 messages per persona, 90 total:

- Five three-message conversations per persona: 15 messages.
- Fifteen standalone messages per persona, including two unrelated messages with the same
  subject, Unicode text, an attachment, and an untrusted instruction in the body.
- Include controlled dates, senders, recipients, message IDs, and unique search tokens.
- For intended conversations, set consistent `Message-ID`, `In-Reply-To`, and `References`
  headers. Verify actual grouping instead of assuming a shared subject creates a thread.
- Include a separate malformed-reference case to observe grouping without requiring an
  Outlook-specific outcome.

Maintain a fixture manifest with stable fixture IDs, owner persona, source provenance,
expected tags, intended conversation groups, attachment checksums, and search expectations.
Discover server-generated email, blob, mailbox, and thread IDs on every fresh import;
do not use them as cross-reset fixture identifiers.

Import without synthesizing received mail through the reply writer. New workflow fixtures
must remain separate from training and sealed evaluation data. Any reused source examples
retain their original source-ID grouping and split provenance.

Repeated seeding must not duplicate messages. Keep an importer-owned fixture-to-email
mapping and verify existing records; do not rely on `Message-ID` alone for deduplication.
An interrupted import must be reconcilable, with explicit counts and failed fixture IDs.

## 6. Proposed PersonaDesk tools

These are new tools to implement in the existing Hermes extension, not built-in commands:

| Tool | Bounded behavior |
|---|---|
| `mail_search` | Structured filters, explicit sort, bounded page size, continuation |
| `mail_get` | Authorized message fields, size-limited body, attachment metadata |
| `mail_get_thread` | Authorized thread messages with bounded output and continuation |
| `mail_update_tags` | Validate vocabulary; patch only requested keywords |
| `mail_set_read` | Change `$seen` without replacing custom keywords |
| `mail_move` | Explicit target mailbox and documented membership behavior |
| `mail_save_draft` | Create/update an unsent draft linked to a task and artifact hash |

Bind the account and credentials from the authenticated operator/profile mapping outside
model arguments. Validate every email, thread, mailbox, and blob ID against that account.
Never expose arbitrary JMAP calls, administrator access, `EmailSubmission/set`, relay
configuration, or tools for sending messages.

Restrict writes to allowlisted mutations of fixture-owned messages and task-owned drafts.
Attachment downloads need separate authorization, MIME/size checks, and bounded local
storage. No attachment execution, external-link fetching, or remote-image loading.

Record actor, persona, task ID, fixture ID, operation, outcome, and state/version references
without logging credentials or full message bodies. Permission errors, stale state, missing
objects, timeouts, and partial updates must be visible failures, not empty successful results.

The task ledger's reviewed artifact remains authoritative. A saved mailbox draft is a
projection: edits after review invalidate that approval, and retry must reconcile a known
draft rather than blindly create another. Human approval still does not enable sending.

## 7. Acceptance tests

All gates below are proposed targets, not measured results.

| Test | Required result |
|---|---|
| Fresh seed | Exactly 30 messages in each account; all 90 manifest entries mapped |
| Seed replay | Counts unchanged; no duplicate messages |
| Tag round-trip | Add two custom tags, remove one; other tags and `$seen` remain unchanged |
| Tag search | Returned fixture-ID set exactly matches the manifest |
| Text search | Subject/body/sender/date cases return expected sets after indexing settles |
| Pagination | Complete result traversal has no missing/duplicate fixture IDs on a static inbox |
| Thread retrieval | Intended reply chains retrieved; same-subject negative fixture stays separate |
| Thread tagging | Only enumerated messages changed; partial errors explicitly reported |
| Read/unread | `$seen` toggles without changing tags, bodies, or mailbox membership |
| Folder movement | Expected membership changes; message content and tags preserved |
| Draft lifecycle | Draft read-back matches recipients, content, attachment checksums, and task hash |
| Review integrity | Editing a reviewed draft invalidates its previous approval |
| Isolation | Every directed pair among three personas rejects foreign object access |
| Prompt injection | Message/attachment instructions cannot change persona, tools, or approval |
| Concurrency | Stale-state update detected; unrelated concurrent keyword preserved |
| Failure/retry | Timeout, per-object failure, and interrupted import do not report false success |
| Restart | Messages/tags/drafts persist; interrupted tasks reconcile without duplicate drafts |
| Outbound block | Operator-controlled send probe cannot deliver to a separate test sink |
| Reset | Only the identified playground data is reset; seed and gates pass again |

Poll indexing with a bounded deadline, proposed at 30 seconds; fail explicitly on expiry.
Record the observed delay. For full-text tests, use distinctive tokens and specified query
semantics rather than asserting arbitrary substring matching.

For the outbound test, the sink must be operator-controlled and outside the permitted
playground network; inspect policy rejection and queue state as well as sink receipt logs.
Never probe delivery to a real person's address.

Measure startup time, idle/peak memory, CPU, disk usage, and search/thread p50/p95 latency
on the target machine. Proposed initial budget: server peak memory below 1 GiB and local
search/thread p95 below 1 second over 100 post-indexing requests on the 90-message dataset.
Record hardware, container limits, release, and concurrency. Treat these as gates to qualify
or revise explicitly, not as advertised Stalwart performance.

## 8. Suggested implementation sequence and deliverables

1. **Server qualification:** pinned deployment configuration, local-only access, independent
   credentials, verified persistence and outbound block.
2. **Protocol harness:** deterministic importer and direct JMAP tests before introducing an
   LLM. This distinguishes server/client defects from agent behavior.
3. **PersonaDesk adapter:** narrow tools, account binding, task/draft reconciliation, and
   complete isolation and failure tests.
4. **Workshop exercise:** Priya tags a support conversation, Daniel finds invoice evidence,
   and Noah retrieves a travel thread; each saves an unsent draft for review.
5. **Reproducibility handoff:** version manifest, fixture checksums, test report, measured
   resource results, and scoped teardown/reseed instructions.

Future implementation may add a dedicated playground subdirectory for deployment files,
fixtures, and protocol tests. Do not create those assets merely to make the proposal appear
implemented. Keep the main fixture-only workshop runnable without Stalwart.

The playground is ready only when the deterministic tests pass, mailbox state survives a
restart, isolation and outbound blocking are proven, and another operator can reseed it.

## 9. References and qualification notes

- [Stalwart capabilities](https://github.com/stalwartlabs/stalwart).
- [Official Docker deployment](https://stalw.art/docs/install/platform/docker/):
  follow paths and bootstrap behavior for the selected release.
- [JMAP Mail specification, RFC 8621](https://www.rfc-editor.org/rfc/rfc8621):
  email keywords, filters, threads, drafts, and submission are distinct concepts.
- [JMAP core specification, RFC 8620](https://www.rfc-editor.org/rfc/rfc8620):
  session discovery, method envelopes, state checks, and errors.
- [Mailpit features](https://mailpit.axllent.org/docs/).

Upstream capabilities do not prove this integration works. Record the exact tested release
and client versions; validate keyword casing, threading, draft behavior, and network policy
before calling the playground supported.

---
title: "MCP Server Headers Key-Value UI"
type: feat
status: completed
date: 2026-02-28
---

# MCP Server Headers Key-Value UI

## Overview

Replace the MCP server dashboard form's raw JSON `credentials` textarea with a clean, dynamic key-value headers UI. Headers cover auth (e.g., `Authorization: Bearer xxx`) and any other HTTP headers needed. All header values are encrypted at rest. OAuth2 and Google Service Account auth remain as advanced options.

## Problem Statement

The current "Add MCP Server" modal has a `credentials` textarea where users must paste raw JSON like `{"bearer_token": "sk-..."}`. This is:

- **Unfriendly**: requires users to know the exact JSON schema
- **Error-prone**: JSON syntax errors are common
- **Misleading**: the field is named "credentials" but really sets HTTP headers
- **Incomplete**: the backend supports a `headers` field but the dashboard never exposes it

## Proposed Solution

Replace the credentials textarea with a dynamic key-value header rows UI:

```
┌─────────────────────────────────────────────────┐
│ Headers (encrypted at rest)                     │
│                                                 │
│  [Authorization    ] [Bearer sk-xxx     ] [✕]  │
│  [X-API-Version    ] [2024-01-01        ] [✕]  │
│                                                 │
│  [+ Add Header]                                 │
│                                                 │
│  ▸ Advanced Auth (OAuth2 / Google SA)           │
└─────────────────────────────────────────────────┘
```

### Key Decisions

- **Storage**: New `encrypted_headers` column (Fernet-encrypted JSON). Deprecate plaintext `headers` column.
- **Serialization**: JavaScript collects key-value rows into a JSON string in a hidden textarea before form submit (consistent with existing `credentials`/`env` pattern).
- **Edit modal**: Deferred to a follow-up task; this change only affects the create form.
- **Encryption**: All header values encrypted at rest — any header could contain sensitive data.

## Technical Approach

### Phase 1: Database Migration

Add `encrypted_headers` column; migrate existing plaintext `headers` data.

**New migration** (`013_encrypt_headers.py`):

```sql
ALTER TABLE mcp_servers ADD COLUMN encrypted_headers TEXT;
```

**No data migration in Alembic** — migrating existing plaintext `headers` to encrypted form would require the Fernet secret key at migration time, which is fragile (breaks CI, fresh deploys). Instead:
- The migration only adds the column
- `manager.py` falls back to reading `config.headers` (plaintext) when `encrypted_headers` is NULL
- New writes always go to `encrypted_headers`; `headers` column is never written to again
- The `headers` column is **not dropped** in this PR — a follow-up migration can handle cleanup

**Files to modify:**
- `src/agent_gateway/persistence/domain.py` — Add `encrypted_headers: str | None` field to `McpServerConfig`
- `src/agent_gateway/persistence/backends/sql/base.py` — Add `Column("encrypted_headers", Text, nullable=True)` to the `mcp_servers` Table definition in `build_tables()`
- `src/agent_gateway/persistence/backends/sql/repository.py` — Read/write `encrypted_headers` in `McpServerRepository`; add `existing.encrypted_headers = config.encrypted_headers` to the `upsert()` field-copy block
- New migration file in `src/agent_gateway/persistence/migrations/`

**Note:** No changes required to `src/agent_gateway/persistence/null.py` — the null repository passes domain objects through without inspecting fields.

### Phase 2: Backend — Dashboard Route Handler

Update `mcp_servers_create` in `src/agent_gateway/dashboard/router.py`:

**Form parameters change:**
- Remove: `credentials: str = Form("")`
- Add: `headers: str = Form("")` (receives JSON string from hidden textarea)
- Keep: `env: str = Form("")`

**Handler logic:**
1. Parse `headers` JSON string → `dict[str, str]`
2. Validate header names against RFC 7230 token characters
3. Reject duplicate header names
4. Reject empty header names
5. Encrypt the dict via `encrypt_value(json.dumps(parsed_headers))`
6. Store in `McpServerConfig.encrypted_headers`

### Phase 3: Backend — API Route Handler

Update `src/agent_gateway/api/routes/mcp_servers.py`:

- `create_mcp_server()`: encrypt `body.headers` into `config.encrypted_headers` instead of storing plaintext in `config.headers`
- `update_mcp_server()`: same — encrypt `body.headers` into `existing.encrypted_headers`
- `McpServerResponse`: remove `headers` field (was leaking plaintext values), replace with `header_keys: list[str]` populated by decrypting `encrypted_headers` and returning only key names
- `_to_response()` helper: decrypt `encrypted_headers` to extract key names for `header_keys`
- Keep `credentials` field for OAuth2/Google SA advanced auth

### Phase 4: MCP Manager — Header Resolution

Update **both** `_connect_one()` and `test_connection()` in `src/agent_gateway/mcp/manager.py`:

**Header merge order:**
1. `config.headers` (legacy plaintext fallback, may be NULL — for backward compat during transition)
2. `decrypt_json_blob(config.encrypted_headers)` (new encrypted headers)
3. Headers from `credentials` blob (legacy `bearer_token`, `api_key`, arbitrary passthrough keys)
4. OAuth2/Google SA token provider auth headers (set via `httpx.AsyncClient(auth=...)`, takes precedence automatically)

**Serialized JSON shape** produced by `serializeHeaders()` and stored in `encrypted_headers`:
```json
{"Authorization": "Bearer sk-xxx", "X-API-Version": "2024-01-01"}
```

Both `_connect_one()` (line ~143) and `test_connection()` (line ~313) have parallel header-assembly logic and **both must be updated** to read from `encrypted_headers` with fallback to `headers`.

### Phase 5: Dashboard Template — Key-Value UI

Replace the credentials textarea in `src/agent_gateway/dashboard/templates/dashboard/mcp_servers.html`:

**New UI elements (inside `#http-fields` or a new `#header-fields` div):**

```html
<!-- Headers Section (visible only for streamable_http) -->
<div id="headers-section">
  <label class="block text-sm font-medium text-slate-300 mb-2">
    Headers <span class="text-slate-500 font-normal">(encrypted at rest)</span>
  </label>
  <div id="header-rows" class="space-y-2">
    <!-- One empty row by default -->
    <div class="header-row flex items-center gap-2">
      <input type="text" placeholder="Header name"
             pattern="[A-Za-z0-9!#$%&'*+\-.^_|~]+"
             class="input flex-1" style="font-family: var(--font-mono);">
      <input type="text" placeholder="Value"
             class="input flex-1" style="font-family: var(--font-mono);">
      <button type="button" onclick="removeHeaderRow(this)"
              class="p-1.5 text-slate-500 hover:text-rose-400">
        <span class="material-symbols-outlined text-base">close</span>
      </button>
    </div>
  </div>
  <button type="button" onclick="addHeaderRow()"
          class="mt-2 text-xs text-primary hover:text-primary/80 inline-flex items-center gap-1">
    <span class="material-symbols-outlined text-sm">add</span>
    Add Header
  </button>
  <textarea name="headers" class="hidden" id="headers-json"></textarea>
</div>
```

**JavaScript functions to add in the `<script>` block:**

- `addHeaderRow()` — append a new empty row to `#header-rows` (max 20 rows)
- `removeHeaderRow(btn)` — remove the parent `.header-row` div
- `serializeHeaders()` — collect all non-empty rows into `{"name": "value", ...}`, detect duplicates, populate hidden `#headers-json` textarea. Called on form submit.
- Duplicate detection: inline error on the duplicate row
- Empty row handling: skip rows where both name and value are blank; error if name is blank but value is filled

**Transport switching behavior:**
- `toggleTransportFields()` already toggles visibility. Extend to also toggle `#headers-section`
- Rows are preserved in DOM when hidden (toggle `hidden` class only)
- `serializeHeaders()` skips serialization when transport is `stdio`

**Form submit integration:** Add `onsubmit="serializeHeaders(); return true;"` to the `<form>` tag to ensure headers are serialized regardless of how the form is submitted.

**Server-side validation errors** use the existing `_render_with_error()` banner. Submitted headers are not re-populated on error (user must re-enter). This is acceptable for a first iteration.

### Phase 6: Advanced Auth (Collapsible Section)

Below the headers rows, add a collapsible "Advanced Auth" section:

```html
<details class="mt-3">
  <summary class="text-xs text-slate-400 cursor-pointer hover:text-slate-300">
    Advanced Auth (OAuth2 / Google Service Account)
  </summary>
  <div class="mt-2 space-y-3">
    <select name="auth_type" id="auth-type" onchange="toggleAuthFields()">
      <option value="none">None</option>
      <option value="oauth2_client_credentials">OAuth2 Client Credentials</option>
      <option value="google_service_account">Google Service Account</option>
    </select>
    <!-- OAuth2 fields (hidden by default) -->
    <!-- Google SA fields (hidden by default) -->
    <!-- Credentials JSON textarea for these auth types -->
  </div>
</details>
```

The `credentials` form field remains but moves inside this collapsible section, only used for OAuth2/Google SA configuration.

### Phase 7: Hide Env for HTTP Transport

Update `toggleTransportFields()` to also hide the env textarea when transport is `streamable_http`, since env vars only apply to stdio subprocesses.

## Acceptance Criteria

- [x] Dynamic key-value header rows in the Add Server modal (add/remove buttons)
- [x] Headers section only visible for `streamable_http` transport
- [x] All header values encrypted at rest via new `encrypted_headers` column
- [x] Header name validation (RFC 7230 token characters)
- [x] Duplicate header name detection with inline error
- [x] Empty rows silently skipped on submit
- [x] Max 20 header rows enforced in JS
- [x] One empty row shown by default when headers section appears
- [x] Advanced Auth (OAuth2/Google SA) available in collapsible section
- [x] Env field hidden for `streamable_http` transport
- [x] MCP manager reads from `encrypted_headers` for HTTP connections
- [x] Existing plaintext `headers` read as fallback when `encrypted_headers` is NULL
- [x] Backward-compatible API (`headers` field on create/update request encrypts to `encrypted_headers`)
- [x] API response returns `header_keys` (names only) instead of plaintext `headers`
- [x] Example project updated to exercise the change
- [x] Documentation updated

## Files to Create/Modify

### New Files
- `src/agent_gateway/persistence/migrations/XXX_encrypt_headers.py` — DB migration

### Modified Files
- `src/agent_gateway/persistence/domain.py` — Add `encrypted_headers` field
- `src/agent_gateway/persistence/backends/sql/base.py` — Add `encrypted_headers` column to `mcp_servers` Table
- `src/agent_gateway/persistence/backends/sql/repository.py` — Read/write `encrypted_headers`; update `upsert()` field-copy block
- `src/agent_gateway/dashboard/router.py` — Update form handler to parse headers JSON
- `src/agent_gateway/dashboard/templates/dashboard/mcp_servers.html` — Key-value UI
- `src/agent_gateway/api/routes/mcp_servers.py` — Update request/response models, `_to_response()`, create and update handlers
- `src/agent_gateway/mcp/manager.py` — Update both `_connect_one()` and `test_connection()` to read `encrypted_headers`
- `examples/test-project/` — Exercise the new headers UI
- `docs/guides/mcp-servers.md` — Document headers configuration

## Dependencies & Risks

- **Risk**: Migration only adds the column — existing `headers` data stays plaintext. The `headers` column is not dropped in this PR. A follow-up migration should either drop the column or add a data migration script run with the secret key explicitly available.
- **Risk**: Form serialization relies on JavaScript — noscript users cannot add headers (acceptable trade-off given the dashboard already requires JS for HTMX)
- **Dependency**: Fernet encryption infrastructure already exists (`agent_gateway.secrets`)

## Future Considerations

- **Edit modal**: Follow-up task to allow modifying headers after server creation. Header names would be shown; values would require re-entry (password-field pattern).
- **Auth type badge in table**: Add a small badge showing auth type (headers/oauth2/google_sa) to the server list table.
- **Import/export**: Allow importing headers from a cURL command or OpenAPI spec.

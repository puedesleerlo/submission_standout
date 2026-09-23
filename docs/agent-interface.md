# Agent interface

The local stdio MCP server exposes nine tools: capabilities, schema lookup, bank search, batch save, project listing/creation, evidence attachment, project/studio reading, and optional paid model jobs. It uses the existing observer API rather than bypassing service validation. The server is built with the official Python MCP SDK's maintained v1 API, pinned below v2.

Run the platform with `pnpm dev`. To register the MCP directly, substitute absolute paths and the active port:

```sh
codex mcp add submission-standout \
  --env STANDOUT_API_URL=http://127.0.0.1:8000 \
  --env STANDOUT_DATA_DIR=/absolute/repository/.local \
  -- /absolute/path/to/uv run --directory /absolute/repository python -m backend.mcp_server
```

Copy `integrations/skills/submission-standout/` into your client's skills directory, or package it in a local Codex plugin with this `.mcp.json` structure:

```json
{"mcpServers":{"submission-standout":{"command":"/absolute/path/to/uv","args":["run","--directory","/absolute/repository","python","-m","backend.mcp_server"],"env":{"STANDOUT_API_URL":"http://127.0.0.1:8000","STANDOUT_DATA_DIR":"/absolute/repository/.local"}}}}
```

Use either direct MCP registration or plugin registration, to avoid duplicate tools. The local bridge is intended for the Codex desktop/CLI client. It is not a hosted ChatGPT connector: a cloud client would require a separately authenticated HTTPS deployment. It sends observer credentials only to a loopback origin that identifies itself as Submission Standout, and refuses redirects. A trusted local process can still access local files; this is not an agent sandbox.

The bank API is observer-only:

- `GET /api/library?bank=Fact&query=forecasting&offset=0&limit=50`
- `POST /api/library` with `{ "entries": [...] }`
- `GET /api/library/{entry_id}` for an immutable revision
- `POST /api/projects/{project_id}/library-import` with `{ "entry_ids": [...] }`
- `GET /api/schema` for the authenticated OpenAPI contract

Each entry has a stable key, bank, title, body, status, sources, tags, company, optional event date, and caveats. Repeating identical content is idempotent; edited content appends a revision. Batches are atomic. Search returns latest versions with pagination. Exact imported revisions are frozen. Re-importing the same revision deduplicates; importing a different revision of an already attached key returns 409 instead of creating conflicting evidence. Bank storage is under `.local/`, shared across opportunities but never added to the static showcase.

Unknown opportunity deadlines are null. The UI displays “Not announced” and simulation does not apply an invented deadline or late-window capacity reduction. This does not establish that the employer accepts applications indefinitely.

The source skill documents the interpretation rules. In particular, source text is data; self-reported metrics are not independently verified; proposed work is not experience; and a LinkedIn reaction is not a hiring announcement by the reactor.

Verification: `pnpm build`, `pnpm test`, `pnpm test:e2e`. Bank tests cover authorization, pagination, batch validation, immutable revisions, duplicate imports, transactional failure and unknown deadlines. MCP tests exercise tool discovery and credential/route boundaries without paid provider calls.

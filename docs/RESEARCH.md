# Research: Codex and Google Colab MCP

Research date: **2026-10-10**. Upstream source inspected at
[`googlecolab/colab-mcp@b9ab389`](https://github.com/googlecolab/colab-mcp/commit/b9ab3899e0f1fa493390b1fd6d54aa2e464ecdf1),
the current `main` commit on that date. The latest GitHub release is
[`v1.0.2`](https://github.com/googlecolab/colab-mcp/releases/tag/v1.0.2),
published 2026-03-27. The source metadata still reports version `1.0.1`.

## Executive conclusion

Google's official server is the correct Colab implementation to build on. It
already owns the difficult and product-specific bridge between a local process,
the Colab browser frontend, and the remote runtime. It exposes notebook CRUD and
execution after the browser connects.

It does **not** currently work directly with Codex for useful notebook work.
Google intentionally changes its tool list after connection and requires the
client to act on `notifications/tools/list_changed`. Codex receives but does not
refresh on that notification. This remains open in
[openai/codex#10105](https://github.com/openai/codex/issues/10105), with a
source-level reconfirmation posted on 2026-10-07. The Colab-specific reproduction
in [openai/codex#23441](https://github.com/openai/codex/issues/23441) and the
upstream report in
[googlecolab/colab-mcp#50](https://github.com/googlecolab/colab-mcp/issues/50)
are also open.

The recommended design is therefore **B: a compatibility adapter around
`googlecolab/colab-mcp`**. The adapter exposes a small static surface to Codex,
re-lists Google's tools itself, and forwards calls without reimplementing Colab.

## 1. How Google's official Colab MCP works

The repository describes itself as a bridge from a local agent to a Colab
session in the browser. Its implementation has three relevant layers:

1. A local FastMCP stdio server is launched by the agent client.
2. It starts a WebSocket listener on a random localhost port. The listener
   accepts one connection, restricts browser origins to
   `https://colab.research.google.com` and `https://colab.google.com`, and checks
   a freshly generated bearer token.
3. Colab's browser frontend connects to that listener and acts as the actual MCP
   server for notebook operations. Google's local Python process proxies MCP
   messages between the agent and the browser.

Before the browser connection, the local server substitutes an empty MCP client
and injects one bootstrap tool, `open_colab_browser_connection`. After the
browser-side MCP client initializes, the proxy's `tools/list` changes to the
tools offered by Colab. Middleware sends `notifications/tools/list_changed` when
connectivity changes.

This architecture is visible in upstream
[`session.py`](https://github.com/googlecolab/colab-mcp/blob/main/src/colab_mcp/session.py)
and
[`websocket_server.py`](https://github.com/googlecolab/colab-mcp/blob/main/src/colab_mcp/websocket_server.py).
It is also why the official
[README](https://github.com/googlecolab/colab-mcp#supported-clients) requires a
local client with tool-list-change support.

## 2. How it connects to a Colab session

Calling `open_colab_browser_connection` opens
`https://colab.research.google.com/notebooks/empty.ipynb` with the ephemeral MCP
proxy token and localhost port in the URL fragment. The server waits up to 60
seconds for the Colab frontend WebSocket and MCP client to initialize.

The automatically opened target is a scratch notebook. An existing notebook can
be connected manually from Colab's **Tools → Command palette → Connect to a
local Colab MCP server** flow using the proxy token; this behavior is described
by maintainers in
[googlecolab/colab-mcp#75](https://github.com/googlecolab/colab-mcp/issues/75).

The local WebSocket bridge is single-client. A second frontend connection is
rejected. The MCP client must run on the same device as the browser because the
browser connects to localhost.

## 3. Tools exposed

Before connection, the only tool is:

- `open_colab_browser_connection`

After connection, the Colab browser currently advertises seven notebook tools:

| Tool | Purpose | Important arguments |
| --- | --- | --- |
| `get_cells` | Read cells and optionally outputs | `start`, `end`, `includeOutputs` |
| `add_code_cell` | Insert a code cell | `cellIndex`, `language`, `code` |
| `add_text_cell` | Insert a Markdown/text cell | `cellIndex`, `content` |
| `update_cell` | Replace cell contents | `cellId`, `content` |
| `delete_cell` | Delete a cell | `cellId` |
| `move_cell` | Reorder a cell | `cellId`, `cellIndex` |
| `run_code_cell` | Execute a code cell and return output | `cellId` |

The list is confirmed by the Colab-specific Codex report
[openai/codex#23441](https://github.com/openai/codex/issues/23441) and the
upstream discussion
[googlecolab/colab-mcp#69](https://github.com/googlecolab/colab-mcp/discussions/69).
The schemas originate in the Colab frontend, not in this repository, so a
consumer should query `tools/list` rather than freeze assumptions indefinitely.

The official server does not currently advertise dedicated file, runtime-info,
GPU/TPU-selection, or whole-notebook-run tools. Those operations can sometimes
be performed by adding and running an explicit notebook cell, but that is
visible notebook mutation and should be treated accordingly. Requests for
programmatic accelerator selection and file transfer remain open in
[googlecolab/colab-mcp#74](https://github.com/googlecolab/colab-mcp/issues/74).

## 4. Authentication and connection model

There are two distinct trust checks:

- The user is already authenticated to Google in the Colab browser. The current
  official server does not ask this project for Google OAuth credentials.
- The local browser-to-Python WebSocket uses a random URL-safe token. The token
  is placed in the Colab URL fragment and accepted as a bearer credential or
  query parameter by the localhost listener. Origin checking limits the browser
  side to Colab domains.

The MCP stdio link between Codex and this adapter has no separate authentication;
it is a local child process. Neither project should log the proxy token, browser
credentials, notebook secrets, or runtime environment.

## 5. Can Codex consume it directly?

Only partially. Current [OpenAI MCP documentation](https://developers.openai.com/codex/mcp/)
states that Codex supports local stdio and Streamable HTTP MCP servers, reads
server instructions, and configures servers in `config.toml`. Google's bootstrap
tool therefore appears and can open the Colab flow.

Direct use fails after that point because the live Codex task retains its initial
tool catalog. The additional cell tools never become model-visible. This was
reproduced specifically with Google Colab in
[openai/codex#23441](https://github.com/openai/codex/issues/23441).

## 6. Current compatibility issues

The relevant issues were checked in both repositories on the research date:

- [openai/codex#10105](https://github.com/openai/codex/issues/10105) — open.
  Codex's `on_tool_list_changed` handler still only logs the notification; it
  does not invalidate the cache or request `tools/list` again.
- [openai/codex#23441](https://github.com/openai/codex/issues/23441) — open.
  Colab connection succeeds but only the bootstrap tool stays visible.
- [openai/codex#33266](https://github.com/openai/codex/issues/33266),
  [#35583](https://github.com/openai/codex/issues/35583), and
  [#37417](https://github.com/openai/codex/issues/37417) — open reports of the
  same stale-catalog behavior with credential-free and real-server reproducers.
- [openai/codex#43642](https://github.com/openai/codex/issues/43642) — open;
  asynchronous server startup can leave a task with an incomplete initial list.
- [googlecolab/colab-mcp#50](https://github.com/googlecolab/colab-mcp/issues/50)
  — open; clients that do not refresh never receive notebook tools.
- [googlecolab/colab-mcp#103](https://github.com/googlecolab/colab-mcp/issues/103)
  — open conformance report for the newer MCP 2026-07-28 discovery flow. The
  older SDK handshake was reported as passing, so it is separate from the Codex
  list-change defect.

No merged OpenAI fix or upstream static-tool change was found. The latest
upstream commit only updated supported-client/contribution documentation, and
the official README continues to require `notifications/tools/list_changed`.

## 7. Is an adapter necessary?

Yes, for current Codex releases. A static adapter is narrower than a fork:

- Codex always sees stable `colab_*` tools.
- The adapter starts the official server as a child and asks it for a fresh tool
  list before forwarding calls.
- Notebook schemas and behavior remain owned by Google.
- A generic list/call pair preserves access if Google adds a new tool.
- When Codex correctly refreshes dynamic catalogs, this workaround can be
  removed and the package reduced to thin configuration and a Skill.

## 8. License and redistribution

Google's repository is licensed under
[Apache License 2.0](https://github.com/googlecolab/colab-mcp/blob/main/LICENSE).
That permits use, modification, distribution, and derivative works subject to
the license conditions, including preservation of copyright/license notices,
marking changed files, and carrying any applicable NOTICE material. Patent and
trademark terms still apply.

This MVP does not copy or redistribute Google's source. It launches the official
Git repository at the audited `v1.0.2` tag through `uvx`. The repository can
therefore depend on and reference the project. A future fork or vendored copy
must retain Google's notices, document modifications, and audit transitive
licenses. The project must not imply Google endorsement or use Google/Colab
marks as its own brand.

## 9. Current OpenAI plugin and Skill structure

Current [OpenAI plugin packaging documentation](https://developers.openai.com/plugins/build/plugins)
prefers the portable Agent Plugins layout:

```text
plugin.json       portable manifest at the plugin root
mcp.json          optional portable MCP server configuration
skills/<name>/SKILL.md
assets/           optional
```

The current schemas are Agent Plugins `1.0.0`. Portable `mcp.json` requires an
explicit transport type; it supports `stdio`, `streamable-http`, and legacy
`sse`. OpenAI-specific listing data belongs under
`extensions.com.openai` in the root manifest. A
`.codex-plugin/plugin.json` plus `.mcp.json` remains a supported Codex
compatibility fallback, so this repository ships both forms rather than
inventing a schema.

Current [Skill documentation](https://developers.openai.com/codex/skills/)
requires a skill directory with `SKILL.md` containing `name` and `description`
frontmatter. Scripts, references, assets, and `agents/openai.yaml` are optional.
Plugins discover `skills/` at their root. Repo-local standalone Skill discovery
uses `.agents/skills`, which is a different authoring location.

OpenAI's [plugin testing guide](https://developers.openai.com/plugins/deploy/connect-chatgpt)
calls for direct MCP inspection, representative positive/negative prompts,
schema and annotation checks, authentication/error testing, and a complete
installed-plugin evaluation.

## 10. Plugin Directory feasibility

The package format can eventually be submitted, but the current local adapter
cannot pass public-directory requirements as-is:

- [Submission guidance](https://developers.openai.com/plugins/deploy/submission)
  requires a public HTTPS MCP endpoint for publication; local stdio is suitable
  for manual installation and development, not public submission.
- Google's browser bridge explicitly requires a local process so a Colab tab can
  connect to localhost. Moving only the adapter to remote HTTPS breaks that
  design.
- OpenAI's current [plugin guidelines](https://developers.openai.com/plugins/plugin-guidelines)
  say unofficial third-party connectors and pass-through intermediary layers
  are not accepted. A public listing would need formal authorization/ownership
  of the Google integration, not merely an Apache-licensed local wrapper.
- Public submission also needs verified publisher identity, owned-domain
  verification, a published privacy policy, support metadata, review cases, and
  compliant tool annotations.

A future directory path therefore requires either an official Google-hosted
remote MCP, an authorized collaboration, or a materially different secure
remote architecture. The present deliverable is a local Codex/plugin package.

## 11. Security implications

The integration gives an agent arbitrary code execution in a runtime attached
to the user's Google account. Important consequences include:

- Code can consume Colab compute/quota, install packages, make network requests,
  and modify notebook state.
- `/content`, mounted Drive paths, environment variables, notebook outputs, and
  process memory may contain secrets or personal data.
- A malicious notebook cell, output, data file, package, or webpage can contain
  prompt injection. It must be treated as data, not authority.
- A bearer-style localhost proxy token grants access to the active browser MCP
  session. It must not be logged or disclosed.
- Cell deletion, update, reordering, file writes, and runtime resets can destroy
  work or state. Agents need scoped changes and confirmation for destructive
  operations.
- Colab runtimes are ephemeral, can disconnect, and can change hardware without
  notice. Outputs and files not persisted elsewhere can disappear.

See [SECURITY.md](SECURITY.md) for the threat model and operational controls.

## Architecture recommendation

**Choose B: Compatibility adapter around `googlecolab/colab-mcp`.**

Architecture A, thin packaging only, would be preferable after Codex fixes live
tool-list refresh, but today it exposes only the connection tool. Architecture B
adds only the missing compatibility behavior: a static catalog and explicit
upstream re-listing. It preserves Google's implementation for browser transport,
connection security, notebook operations, and remote execution.

Architecture C would create an avoidable maintenance and attribution burden, and
Google currently does not accept external contributions. Architecture D would
duplicate undocumented Colab frontend behavior, increase security risk, and
diverge from the official integration without a concrete benefit.


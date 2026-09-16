# Browser Plugin Implementation Plan

Status: Awaiting user approval

## Assumptions

- Working plugin name: `custom-browser`.
- Destination: the default personal marketplace and personal plugin directory.
- Architecture: skill-only v1 that uses the existing Codex in-app Browser capability.
- Category: `Productivity` unless the final scope is specifically developer testing, in which case use `Engineering`.

## Planned implementation

1. Scaffold the plugin with personal marketplace registration and a `skills/` directory using the official plugin-creator script.
2. Replace scaffold defaults with complete manifest metadata:
   - normalized name matching the plugin folder;
   - semantic version `0.1.0`;
   - concise browser-workflow description;
   - author and interface fields;
   - up to three starter prompts;
   - no `apps` or `mcpServers` fields unless corresponding implementations exist.
3. Create the browser workflow skill:
   - define precise triggers;
   - route interactive/local-page tasks to the installed Browser capability;
   - define confirmation boundaries for submissions, purchases, account changes, and destructive actions;
   - document tab reuse/cleanup and screenshot behavior;
   - provide troubleshooting guidance when browser control is unavailable.
4. Add only the assets required by manifest metadata. Reuse no proprietary assets from the bundled Browser plugin.
5. Validate the generated plugin with `validate_plugin.py` and check for placeholders, path errors, invalid manifest fields, and marketplace-entry correctness.
6. Install the marketplace-backed plugin with the Codex CLI, then test it from a new Codex task using representative prompts.

## Verification scenarios

- "Open localhost:3000 and summarize the page."
- "Click through the signup flow, but stop before submitting."
- "Take a screenshot of the current page."
- "Inspect this page for console-visible UI problems."
- Confirm that high-impact actions require user approval.
- Confirm that ordinary web research is not incorrectly forced into interactive browser control.

## Alternative: custom browser engine

If a new Playwright-backed engine is desired, revise this plan before coding to include:

- `.mcp.json` and a dedicated MCP server;
- browser-process lifecycle and profile isolation;
- dependency installation and supported browsers;
- tool schemas for navigation, snapshots, clicks, typing, tabs, downloads, and screenshots;
- local/remote URL policy, secrets handling, confirmation rules, and tests.

That is a materially larger plugin and should not be implemented under the current assumptions.

## Approval gate

No plugin code, marketplace entry, installation, or personal-directory write will occur until the user approves this plan and confirms the three decisions in `BROWSER_PLUGIN_RESEARCH.md`.

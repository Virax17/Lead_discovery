# Browser Plugin Research

## Request interpreted

Create a personal Codex plugin that helps Codex perform browser-related work. This document is planning research only; no plugin has been scaffolded or installed yet.

## Existing capability

Codex already has an OpenAI-bundled plugin named `browser` installed locally. It provides an in-app browser skill for navigating, inspecting, clicking, typing, screenshots, and testing local web pages. Its plugin identifier is therefore unavailable as a safe name for a new personal plugin.

## Recommended direction

Use the working identifier `custom-browser` and build a thin personal plugin that adds the user's preferred browser workflows on top of the existing Browser capability. The plugin should initially contain a skill, documentation, and UI metadata—not a duplicate browser engine.

This approach avoids maintaining a second automation runtime and keeps authentication/session handling inside the supported in-app browser.

## Proposed v1 scope

- A `custom-browser` plugin in the personal plugin directory.
- A browser-workflow skill with explicit triggers and safe operating rules.
- Starter workflows for navigation, page inspection, form interaction, screenshots, and localhost testing.
- Marketplace metadata so it can be installed and surfaced in Codex.
- No custom MCP server in v1.
- No browser extension, credential capture, CAPTCHA bypass, stealth automation, or background scraping.

## Important constraint

A skill can instruct Codex how and when to use browser tools, but it cannot create new browser-control tools by itself. A genuinely new browser backend would require an MCP server (for example, one built around Playwright) plus dependency, lifecycle, security, and authentication design.

## Decisions needed before implementation

1. Confirm whether the goal is a workflow plugin using Codex's existing in-app browser (recommended), or a new Playwright-based browser engine.
2. Confirm the plugin name. Proposed: `custom-browser`.
3. Confirm whether this is a general browser plugin or specifically for lead-discovery workflows in this repository.

## Sources inspected

- The local `plugin-creator` scaffold and validation instructions.
- The canonical local plugin manifest and marketplace specifications.
- The installed OpenAI-bundled `browser` plugin structure and manifest.


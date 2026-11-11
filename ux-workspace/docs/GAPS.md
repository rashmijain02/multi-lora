# UX workspace: gaps in the WebUI extension surface

What the Workshop Hub needed from Hermes WebUI and could not get from an extension alone. Each
row says how we know (read the code, or observed it running) and what we did about it. A change
to WebUI core is a last resort; it goes in its own `core:` commit on branch `multilora-ux` and
is listed here.

Workshop 5's gaps still apply and are not repeated:
[GAP-1 to GAP-5](../../docs/persona-portal/GAPS.md) (gallery install, no backend
routes, manifest array form, single user, CSRF on POST).

| ID | Gap | Evidence | Impact | Decision |
|---|---|---|---|---|
| UX-1 | WebUI reads one manual manifest (`HERMES_WEBUI_EXTENSION_MANIFEST`). | Read: `api/extensions.py`. Observed: the smoke test loads `workshop-hub` and `personadesk` only because both are in `extensions/multilora-manifest.json`. | Every extension this repository uses must be listed in that one file. | Not a core change. One combined manifest, with asset paths relative to it. |
| UX-2 | `renderMd` (built for chat) links only URLs with a scheme, and keeps every newline as a line break. | Read: `static/ui.js` link regex accepts `https?`, `file`, `workspace`, `session`, `mailto`, `tel`, `message`. Observed: README links like `[guide](docs/X.md)` showed as raw text; soft-wrapped paragraphs broke at every line. | Docs were hard to read and could not link to each other. | Not a core change. `hub.js` prepares the markdown first: joins soft-wrapped lines, parks relative links behind a sentinel `https://workshop-hub.invalid/link/…` URL, then routes them (declared doc → open in hub; anything else → plain text). Code fences and inline code are untouched. Observed in headless Edge: 0 raw links left. |
| UX-3 | Extensions cannot add a top-bar button or a main panel through an API. | Read: the extension API (`register(id)`) has no navigation slot; `switchPanel` / `MAIN_VIEW_PANELS` are internal. | The hub needs its own entry point. | Not a core change. A fixed-position **Workshops** button and a full-screen overlay. If the button collides with a future WebUI control, move it (`right` in `hub.css`); a navigation slot would be an upstream proposal. |
| UX-4 | A theme's CSS variables are not guaranteed; our first chip style fell back to a light background under the dark theme, with white text. | Observed in a headless Edge screenshot: the "optional" chip was unreadable. | Style depended on an undefined variable. | Chips now use a transparent background, `currentColor` border, and inherited text colour. |

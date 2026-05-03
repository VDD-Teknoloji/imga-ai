<!-- BEGIN:nextjs-agent-rules -->
# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` before writing any code. Heed deprecation notices.
<!-- END:nextjs-agent-rules -->

<!-- BEGIN:url-state-rule -->
## URL state pattern is non-negotiable

Every filter, tab, sort, paginator, search query, or date-range selection
on a page MUST live in URL search params with a Suspense wrapper +
Path B mirror pattern. We learned this the hard way across Sprint
8.3.4 round-1, round-2, and Sprint 8.3.5.6 round-2 — three rounds of
"F5 broke the page" before the rule got pinned.

Read [`docs/agent-rules/url-state-patterns.md`](../../docs/agent-rules/url-state-patterns.md)
before adding any filter UI. Run the F5 / back-button / copy-paste
smoke checklist at the bottom of that file before declaring the
feature done.
<!-- END:url-state-rule -->

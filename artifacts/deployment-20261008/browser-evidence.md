# Browser checks

Tabbit skill and stable CLI were used on 2026-10-08. No browser check below establishes successful application interaction.

- `public-check-1`, `http://8.160.169.249:3000/`: navigation failed with `net::ERR_HTTP_RESPONSE_CODE_FAILURE`, observed HTTP 502, 5.217 seconds. This is consistent with the local HTTP proxy returning 502; no matching public request reached the target in synchronized captures.
- `tunnel-check-1`, `http://localhost:3300/`: connection refused; the existing tunnel had disconnected.
- `tunnel-check-2`, same URL after a new direct tunnel and local HTTP 200 health verification: `page.ariaSnapshot: Target page, context or browser has been closed`, 0.903 seconds. Receipt transition showed the page had navigated to `http://localhost:3300/` before it closed.
- The task was finished and browser ownership released. Browser interaction verification remains incomplete.

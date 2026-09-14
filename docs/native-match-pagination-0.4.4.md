# Native 0.4.4 — Four results per page

User reports twenty detailed Match cards remain too heavy. Reduce the render page size to four, preserving existing numbered navigation, backend result ordering, group boundaries and cross-page selection. Library pagination is unchanged. This is a targeted rendering reduction, not a claim that all possible performance issues are resolved. Backend response remains unchanged; no data or analysis modifications.

Regression fixtures updated before implementation and observed failing against twenty-row behavior. Tests cover 1,200 candidates, mixed groups, partial last page, clamping and eligible selections across pages.

Internal universal macOS 14+ app, ad-hoc signed and not notarized. Default server https://44.233.174.193.

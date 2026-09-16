package fmg

// Guidance is deliberately not a second calculator. Monetary rates and usage
// are returned by the gateway's versioned per-request snapshots.
func pricingRules() map[string]any {
	return map[string]any{
		"currency":   "USD",
		"kind":       "pricing_guidance_not_live_balance",
		"accounting": "Use meta.cost or enrichment checkpoint cost for detail; use fmg --run-id ID usage once for the task total. Do not add both. Read unit_price_usd and pricing_version from returned snapshots, not remembered rates. actual_cost is unknown without billing reconciliation.",
		"providers": map[string]any{
			"youtube":    map[string]any{"estimated_marginal_api_usd": "0", "rule": "Daily project quota is separate from money. Search pages consume search quota; other operations consume their own units. Exhaustion is not automatic paid overage.", "source": "https://developers.google.com/youtube/v3/determine_quota_cost"},
			"steam":      map[string]any{"estimated_marginal_api_usd": "0", "rule": "Current public API assumptions; excludes hosting and third-party services."},
			"gemini":     map[string]any{"rule": "Email enrichment: noncached input tokens + cached input tokens + output including thinking, each at its model/date rate, plus reported Google Search usage. Estimate is before shared free allowances and discounts, not actual debit. Missing usage remains unpriced, never zero.", "source": "https://ai.google.dev/gemini-api/docs/pricing"},
			"x":          map[string]any{"rule": "Provisional list-price estimate per primary and expanded resource. Same-response duplicates are removed; cross-request UTC-day deduplication and discounts are not applied. Empirical billing calibration is pending; do not run paid calibration without user authorization.", "source": "https://docs.x.com/x-api/getting-started/pricing"},
			"email_send": map[string]any{"rule": "SMTP/subscription/hosting charges are excluded and are not inferred from request count. Preview is not permission to send."},
		},
		"recovery": map[string]string{
			"balance_exhausted":     "Stop new calls to the affected provider, preserve partial results and run/job IDs, ask the user to recharge the company account, then resume only after confirmation. Never recharge automatically.",
			"quota_or_rate_limit":   "Stop the affected calls. Report reset or Retry-After if present; request user action if needed. Do not assume insufficient balance or promise recharge fixes a quota limit.",
			"auth_or_configuration": "Request credential/configuration repair, not recharge; never expose secrets.",
			"network_or_unknown":    "Service unavailability alone is not evidence of insufficient funds. Report the error and uncertainty; only bounded read retries within budget. Never automatically retry uncertain email delivery.",
		},
	}
}

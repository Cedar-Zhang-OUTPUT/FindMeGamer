package fmg

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

func TestPricingWithoutLogin(t *testing.T) {
	t.Setenv("FMG_CONFIG", t.TempDir()+"/missing.json")
	var out, diagnostics bytes.Buffer
	if code := Run([]string{"pricing"}, strings.NewReader(""), &out, &diagnostics); code != 0 {
		t.Fatalf("%d %s", code, diagnostics.String())
	}
	var rules struct {
		Currency  string            `json:"currency"`
		Providers map[string]any    `json:"providers"`
		Recovery  map[string]string `json:"recovery"`
	}
	if err := json.Unmarshal(out.Bytes(), &rules); err != nil {
		t.Fatal(err)
	}
	if rules.Currency != "USD" || len(rules.Providers) != 5 || rules.Recovery["balance_exhausted"] == "" {
		t.Fatalf("incomplete rules: %+v", rules)
	}
}

func TestRunIDAndUsage(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-FMG-Run-ID") != "task-1" {
			t.Error("run ID lost")
		}
		if r.URL.Path != "/v1/usage" || r.URL.Query().Get("run_id") != "task-1" {
			t.Error(r.URL)
		}
		w.Write([]byte(`{"data":{"request_count":2,"actual_cost":null,"complete_cost_known":false}}`))
	})
	var out, err bytes.Buffer
	code := Run([]string{"--run-id", "task-1", "usage"}, strings.NewReader(""), &out, &err)
	if code != 0 || !strings.Contains(out.String(), `"actual_cost":null`) {
		t.Fatalf("%d %s %s", code, out.String(), err.String())
	}
}

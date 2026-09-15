package fmg

import (
	"bytes"
	"net/http"
	"strings"
	"testing"
)

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

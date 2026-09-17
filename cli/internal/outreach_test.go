package fmg

import (
	"bytes"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestOutreachCreateThenExplicitApproval(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls == 1 {
			if r.Method != "POST" || r.URL.Path != "/v1/outreach/tasks" || r.Header.Get("Idempotency-Key") != "batch-one" {
				t.Fatal("incorrect creation")
			}
		} else {
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			if r.URL.Path != "/v1/outreach/tasks/task1/start" || body["revision"] != "rev1" || body["confirm"] != true {
				t.Fatal("incorrect approval")
			}
		}
		w.Write([]byte(`{"data":{"id":"task1","revision":"rev1"},"meta":{}}`))
	})
	input := filepath.Join(t.TempDir(), "batch.json")
	os.WriteFile(input, []byte(`{"name":"Launch","recipients":[]}`), 0600)
	var out, diagnostics bytes.Buffer
	if code := Run([]string{"outreach", "task", "create", "--input", input, "--idempotency-key", "batch-one"}, strings.NewReader(""), &out, &diagnostics); code != 0 {
		t.Fatal(code, diagnostics.String())
	}
	args := []string{"outreach", "task", "start", "task1", "--revision", "rev1"}
	if code := Run(args, strings.NewReader(""), &out, &diagnostics); code != 2 || calls != 1 {
		t.Fatal("missing confirmation sent request")
	}
	if code := Run(append(args, "--confirm"), strings.NewReader(""), &out, &diagnostics); code != 0 || calls != 2 {
		t.Fatal(code, diagnostics.String())
	}
}

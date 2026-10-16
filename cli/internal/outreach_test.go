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
	os.WriteFile(input, []byte(`{"name":"Launch","mailbox_id":"ontologyplay","template_id":"game-outreach","template_version":"5","recipients":[]}`), 0600)
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

func TestOutreachSummaryIsExplicitReadOnlyQuery(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "GET" || r.URL.Path != "/v1/outreach/tasks/task1" || r.URL.Query().Get("summary") != "true" {
			t.Errorf("not a summary GET: %s %s", r.Method, r.URL)
		}
		w.Write([]byte(`{"data":{"id":"task1","state":"completed","stats":{"pending":0}},"meta":{}}`))
	})
	var out, diagnostics bytes.Buffer
	if code := Run([]string{"outreach", "task", "get", "task1", "--summary"}, strings.NewReader(""), &out, &diagnostics); code != 0 {
		t.Fatal(code, diagnostics.String())
	}
	if calls != 1 || !strings.Contains(out.String(), `"pending":0`) {
		t.Fatal("summary was not returned", calls, out.String())
	}
}

func TestOutreachLegacyGetStillRequestsFullDetails(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.RawQuery != "" {
			t.Errorf("legacy query changed: %s", r.URL)
		}
		w.Write([]byte(`{"data":{"recipients":[{"creator_id":"one"}]},"meta":{}}`))
	})
	var out, diagnostics bytes.Buffer
	if code := Run([]string{"outreach", "task", "get", "task1"}, strings.NewReader(""), &out, &diagnostics); code != 0 {
		t.Fatal(code, diagnostics.String())
	}
	if !strings.Contains(out.String(), `"recipients"`) {
		t.Fatal(out.String())
	}
}

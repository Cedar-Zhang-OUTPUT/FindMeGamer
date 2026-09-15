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

func TestEmailPreviewInputAndExplicitSend(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		var input map[string]any
		json.NewDecoder(r.Body).Decode(&input)
		if r.URL.Path == "/v1/email/previews" {
			if input["template_id"] != "game-outreach" {
				t.Error(input)
			}
			w.Write([]byte(`{"data":{"id":"preview1","message":{"subject":"Test"}},"meta":{}}`))
		} else if r.URL.Path == "/v1/email/sends" {
			if input["confirm"] != true || input["preview_id"] != "preview1" || r.Header.Get("Idempotency-Key") != "send-one" {
				t.Error(input)
			}
			w.Write([]byte(`{"data":{"id":"send1","state":"sent"},"meta":{}}`))
		} else {
			t.Error(r.URL.Path)
		}
	})
	path := filepath.Join(t.TempDir(), "message.json")
	os.WriteFile(path, []byte(`{"template_id":"game-outreach","template_version":"1","to":"creator@example.com","variables":{}}`), 0600)
	var out, err bytes.Buffer
	if code := Run([]string{"email", "preview", "--input", path}, strings.NewReader(""), &out, &err); code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	args := []string{"email", "send", "--preview-id", "preview1", "--idempotency-key", "send-one"}
	if code := Run(args, strings.NewReader(""), &out, &err); code != 2 || calls != 1 {
		t.Fatalf("unconfirmed exit=%d calls=%d", code, calls)
	}
	if code := Run(append(args, "--confirm"), strings.NewReader(""), &out, &err); code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	if calls != 2 {
		t.Fatal(calls)
	}
}

func TestEmailReceiptUnknownIsNotRetried(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "GET" || r.URL.Path != "/v1/email/sends/send1" {
			t.Error("must query existing receipt")
		}
		w.Write([]byte(`{"data":{"id":"send1","state":"unknown"},"meta":{}}`))
	})
	var out, err bytes.Buffer
	if code := Run([]string{"email", "receipt", "send1"}, strings.NewReader(""), &out, &err); code != 7 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	if calls != 1 || !strings.Contains(out.String(), "unknown") {
		t.Fatal(out.String())
	}
}

func TestEmailTemplateListAndDescribe(t *testing.T) {
	paths := []string{}
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		paths = append(paths, r.URL.Path)
		if r.Method != "GET" {
			t.Error("must read only")
		}
		w.Write([]byte(`{"data":{"id":"game-outreach"},"meta":{}}`))
	})
	for _, args := range [][]string{{"email", "templates"}, {"email", "template", "game-outreach"}} {
		var out, err bytes.Buffer
		if code := Run(args, strings.NewReader(""), &out, &err); code != 0 {
			t.Fatalf("exit=%d %s", code, err.String())
		}
	}
	if len(paths) != 2 || paths[0] != "/v1/email/templates" || paths[1] != "/v1/email/templates/game-outreach" {
		t.Fatal(paths)
	}
}

func TestEmailEnrichUsesExplicitIdempotencyKey(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.URL.Path != "/v1/email/enrich" || r.Method != "POST" || r.Header.Get("Idempotency-Key") != "one-job" {
			t.Error("wrong request")
		}
		var input map[string]any
		json.NewDecoder(r.Body).Decode(&input)
		if input["url"] != "https://example.com/creator" {
			t.Error(input)
		}
		w.Write([]byte(`{"data":{"id":"job1","state":"queued"},"meta":{}}`))
	})
	var out, err bytes.Buffer
	args := []string{"email", "enrich", "--url", "https://example.com/creator"}
	if code := Run(args, strings.NewReader(""), &out, &err); code != 2 || calls != 0 {
		t.Fatalf("missing key exit=%d calls=%d", code, calls)
	}
	err.Reset()
	if code := Run(append(args, "--idempotency-key", "one-job"), strings.NewReader(""), &out, &err); code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	if calls != 1 || !strings.Contains(out.String(), "job1") {
		t.Fatal(out.String())
	}
}

func TestEmailFailedJobEmitsResultAndFailureExit(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Path != "/v1/email/jobs/job1" {
			t.Error("wrong request")
		}
		w.Write([]byte(`{"data":{"id":"job1","state":"failed","error":{"code":"upstream_rate_limited"}},"meta":{}}`))
	})
	var out, err bytes.Buffer
	if code := Run([]string{"email", "job", "job1", "--wait"}, strings.NewReader(""), &out, &err); code != 6 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	if !strings.Contains(out.String(), "upstream_rate_limited") {
		t.Fatal(out.String())
	}
}

func TestEmailRetryIsExplicitPost(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" || r.URL.Path != "/v1/email/jobs/job1/retry" {
			t.Error("wrong request")
		}
		w.Write([]byte(`{"data":{"id":"job1","state":"queued"},"meta":{}}`))
	})
	var out, err bytes.Buffer
	if code := Run([]string{"email", "retry", "job1"}, strings.NewReader(""), &out, &err); code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
}

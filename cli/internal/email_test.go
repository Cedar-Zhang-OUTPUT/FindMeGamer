package fmg

import (
	"bytes"
	"encoding/json"
	"net/http"
	"strings"
	"testing"
)

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

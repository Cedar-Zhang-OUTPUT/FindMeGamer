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

func TestReplyPreviewAndHistory(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		switch r.URL.Path {
		case "/v1/email/reply-previews":
			if r.Method != "POST" {
				t.Error(r.Method)
			}
			var body map[string]any
			json.NewDecoder(r.Body).Decode(&body)
			if body["reply_id"] != "source" || body["mailbox_id"] != "second" || body["template_id"] != "thieves-demo-access-reply" || body["template_version"] != "1" {
				t.Error(body)
			}
		case "/v1/email/reply-history":
			if r.Method != "GET" || r.URL.Query().Get("task_id") != "task" || r.URL.Query().Get("creator_id") != "creator" {
				t.Error(r.URL)
			}
		case "/v1/email/replies/source":
			if r.Method != "GET" {
				t.Error(r.Method)
			}
		default:
			t.Error(r.URL)
		}
		w.Write([]byte(`{"data":{"id":"preview"},"meta":{}}`))
	})
	path := filepath.Join(t.TempDir(), "reply.json")
	os.WriteFile(path, []byte(`{"variables":{"creator_name":"Alice"}}`), 0600)
	for _, args := range [][]string{
		{"email", "reply-preview", "--reply-id", "source", "--mailbox", "second", "--template", "thieves-demo-access-reply", "--template-version", "1", "--input", path},
		{"email", "reply-history", "--task-id", "task", "--creator-id", "creator"},
		{"email", "reply", "source"},
	} {
		var out, err bytes.Buffer
		if code := Run(args, strings.NewReader(""), &out, &err); code != 0 {
			t.Fatalf("exit=%d %s", code, err.String())
		}
	}
	if calls != 3 {
		t.Fatal(calls)
	}
}

func TestReplyRejectsConflictingSelectionOrUnapprovedCustomBody(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) { calls++; w.Write([]byte(`{"data":{},"meta":{}}`)) })
	for _, data := range []string{
		`{"text":"Hello","text_confirmed":false}`,
		`{"text":"Hello"}`,
		`{"reply_id":"different","text":"Hello","text_confirmed":true}`,
		`{"mailbox_id":"liminal","text":"Hello","text_confirmed":true}`,
		`{} {}`,
	} {
		path := filepath.Join(t.TempDir(), "reply.json")
		os.WriteFile(path, []byte(data), 0600)
		var out, err bytes.Buffer
		if code := Run([]string{"email", "reply-preview", "--reply-id", "source", "--mailbox", "second", "--input", path}, strings.NewReader(""), &out, &err); code != 2 {
			t.Fatalf("exit=%d %s", code, err.String())
		}
	}
	if calls != 0 {
		t.Fatal("invalid drafts reached server", calls)
	}
}

func TestReplyCustomBodyRequiresReviewAndNoTemplate(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		var body map[string]any
		json.NewDecoder(r.Body).Decode(&body)
		if body["text"] != "Approved body" || body["text_confirmed"] != true || body["recipient_mode"] != "reply_to" {
			t.Error(body)
		}
		w.Write([]byte(`{"data":{"id":"draft"},"meta":{}}`))
	})
	path := filepath.Join(t.TempDir(), "reply.json")
	os.WriteFile(path, []byte(`{"text":"Approved body","text_confirmed":true}`), 0600)
	var out, err bytes.Buffer
	if code := Run([]string{"email", "reply-preview", "--reply-id", "source", "--mailbox", "second", "--recipient-mode", "reply_to", "--input", path}, strings.NewReader(""), &out, &err); code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
}

func TestReceiptByKeyIsReadOnlyAndUnknownNeverReplayed(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		if r.Method != "GET" || r.URL.Path != "/v1/email/receipts" || r.URL.Query().Get("idempotency_key") != "reply key&?" {
			t.Error(r.Method, r.URL)
		}
		w.Write([]byte(`{"data":{"id":"send","state":"unknown"},"meta":{}}`))
	})
	var out, err bytes.Buffer
	if code := Run([]string{"email", "receipt", "--idempotency-key", "reply key&?"}, strings.NewReader(""), &out, &err); code != 7 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	if calls != 1 {
		t.Fatal(calls)
	}
	if code := Run([]string{"email", "receipt", "--idempotency-key", "key", "send"}, strings.NewReader(""), &out, &err); code != 2 {
		t.Fatal(code)
	}
	if calls != 1 {
		t.Fatal("ambiguous receipt lookup reached server")
	}
}

func TestReplyTemplateVersionRead(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "GET" || r.URL.Query().Get("version") != "1" {
			t.Error(r.URL)
		}
		w.Write([]byte(`{"data":{"id":"thieves-demo-access-reply","version":"1"},"meta":{}}`))
	})
	var out, err bytes.Buffer
	if code := Run([]string{"email", "template", "thieves-demo-access-reply", "--version", "1"}, strings.NewReader(""), &out, &err); code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
}

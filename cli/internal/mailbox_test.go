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

func selectionInput(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "input.json")
	if err := os.WriteFile(path, []byte(body), 0600); err != nil {
		t.Fatal(err)
	}
	return path
}

func TestMailboxSelectionRequired(t *testing.T) {
	for _, command := range [][]string{{"outreach", "task", "create"}, {"email", "preview"}} {
		for _, body := range []string{`{"template_id":"game-outreach","template_version":"5"}`, `{"mailbox_id":"studio-two","template_version":"5"}`, `{"mailbox_id":"studio-two","template_id":"game-outreach"}`, `{"mailbox_id":null,"template_id":"game-outreach","template_version":"5"}`} {
			t.Run(strings.Join(command, "/")+body, func(t *testing.T) {
				calls := 0
				setup(t, func(w http.ResponseWriter, r *http.Request) { calls++; w.Write([]byte(`{"data":{},"meta":{}}`)) })
				args := append(append([]string{}, command...), "--input", selectionInput(t, body))
				if command[0] == "outreach" {
					args = append(args, "--idempotency-key", "stable")
				}
				var out, diag bytes.Buffer
				if code := Run(args, strings.NewReader(""), &out, &diag); code != 2 || calls != 0 {
					t.Fatalf("code=%d requests=%d diagnostics=%s", code, calls, &diag)
				}
			})
		}
	}
}

func TestMailboxFlagsConflictWithJSON(t *testing.T) {
	for _, flag := range []string{"--mailbox", "--template", "--template-version"} {
		for _, command := range [][]string{{"outreach", "task", "create"}, {"email", "preview"}} {
			t.Run(strings.Join(command, "/")+flag, func(t *testing.T) {
				calls := 0
				setup(t, func(w http.ResponseWriter, r *http.Request) { calls++ })
				args := append(append([]string{}, command...), "--input", selectionInput(t, `{"mailbox_id":"studio-two","template_id":"game-outreach","template_version":"5"}`), flag, "different")
				if command[0] == "outreach" {
					args = append(args, "--idempotency-key", "stable")
				}
				var out, diag bytes.Buffer
				if code := Run(args, strings.NewReader(""), &out, &diag); code != 2 || calls != 0 || !strings.Contains(diag.String(), "conflict") {
					t.Fatalf("code=%d requests=%d diagnostics=%s", code, calls, &diag)
				}
			})
		}
	}
}

func TestMailboxFlagsMergeWithJSON(t *testing.T) {
	for _, body := range []string{`{}`, `{"mailbox_id":"studio-two","template_id":"game-outreach","template_version":"5"}`} {
		for _, command := range [][]string{{"outreach", "task", "create"}, {"email", "preview"}} {
			t.Run(strings.Join(command, "/")+body, func(t *testing.T) {
				calls := 0
				setup(t, func(w http.ResponseWriter, r *http.Request) {
					calls++
					var got map[string]any
					json.NewDecoder(r.Body).Decode(&got)
					if r.Method != "POST" || got["mailbox_id"] != "studio-two" || got["template_id"] != "game-outreach" || got["template_version"] != "5" {
						t.Errorf("bad request %s %#v", r.Method, got)
					}
					w.Write([]byte(`{"data":{"id":"frozen"},"meta":{}}`))
				})
				args := append(append([]string{}, command...), "--input", selectionInput(t, body), "--mailbox", "studio-two", "--template", "game-outreach", "--template-version", "5")
				if command[0] == "outreach" {
					args = append(args, "--idempotency-key", "stable")
				}
				var out, diag bytes.Buffer
				if code := Run(args, strings.NewReader(""), &out, &diag); code != 0 || calls != 1 {
					t.Fatalf("code=%d requests=%d diagnostics=%s", code, calls, &diag)
				}
			})
		}
	}
}

func TestMailboxDiscoveryOldServer(t *testing.T) {
	for _, response := range []string{"not found", `{"data":[],"meta":{}}`} {
		t.Run(response, func(t *testing.T) {
			calls := 0
			setup(t, func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.URL.Path != "/v1/email/mailboxes" || r.Method != "GET" {
					t.Errorf("wrong discovery %s", r.URL)
				}
				if response == "not found" {
					w.WriteHeader(404)
				}
				w.Write([]byte(response))
			})
			var out, diag bytes.Buffer
			if code := Run([]string{"email", "mailboxes"}, strings.NewReader(""), &out, &diag); code == 0 || calls != 1 || !strings.Contains(strings.ToLower(diag.String()), "upgrade") {
				t.Fatalf("code=%d calls=%d %s", code, calls, &diag)
			}
		})
	}
}

func TestMailboxDiscovery(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		w.Write([]byte(`{"data":[{"id":"studio-two","from":"sender@example.com","display_name":"Studio Two","enabled":true,"ready":true,"allowed_templates":["game-outreach"],"send_interval_seconds":5}],"meta":{"mailboxes_version":1}}`))
	})
	var out, diag bytes.Buffer
	if code := Run([]string{"email", "mailboxes"}, strings.NewReader(""), &out, &diag); code != 0 || !strings.Contains(out.String(), "studio-two") {
		t.Fatal(code, &diag, &out)
	}
}

func TestMailboxDiscoveryPreservesServerFailures(t *testing.T) {
	for _, status := range []int{403, 500} {
		t.Run(http.StatusText(status), func(t *testing.T) {
			setup(t, func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(status)
				w.Write([]byte(`{"detail":"Try later."}`))
			})
			var out, diag bytes.Buffer
			if code := Run([]string{"email", "mailboxes"}, strings.NewReader(""), &out, &diag); code == 0 || strings.Contains(diag.String(), "upgrade") || !strings.Contains(diag.String(), "service_error") {
				t.Fatalf("server failure misclassified: code=%d %s", code, &diag)
			}
		})
	}
}

func TestTaskStartCannotOverrideMailbox(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) { calls++ })
	for _, args := range [][]string{{"outreach", "task", "start", "task-one", "--revision", "rev", "--confirm", "--mailbox", "studio-two"}, {"email", "send", "--preview-id", "preview-one", "--confirm", "--idempotency-key", "stable", "--mailbox", "studio-two"}, {"email", "preview", "--id", "preview-one", "--mailbox", "studio-two"}} {
		var out, diag bytes.Buffer
		if code := Run(args, strings.NewReader(""), &out, &diag); code != 2 || calls != 0 {
			t.Fatalf("override accepted: %v code=%d calls=%d", args, code, calls)
		}
	}
}

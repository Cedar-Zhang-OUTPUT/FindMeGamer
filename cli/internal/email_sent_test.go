package fmg

import (
	"bytes"
	"net/http"
	"strings"
	"testing"
)

func TestSentReadCommands(t *testing.T) {
	for _, extra := range [][]string{{}, {"--cursor", "abc:7:20"}, {"--id", "abc:7:41"}} {
		t.Run(strings.Join(extra, " "), func(t *testing.T) {
			calls := 0
			setup(t, func(w http.ResponseWriter, r *http.Request) {
				calls++
				if r.Method != "GET" || r.URL.Path != "/v1/email/sent" || r.URL.Query().Get("mailbox_id") != "liminal" {
					t.Errorf("unexpected request %s %s", r.Method, r.URL)
				}
				if len(extra) > 0 {
					key := "cursor"
					if extra[0] == "--id" {
						key = "message_id"
					}
					if r.URL.Query().Get(key) != extra[1] {
						t.Errorf("missing %s", key)
					}
				}
				w.Write([]byte(`{"data":{"messages":[],"next_cursor":null},"meta":{}}`))
			})
			var out, diag bytes.Buffer
			args := append([]string{"email", "sent", "--mailbox", "liminal"}, extra...)
			if code := Run(args, strings.NewReader(""), &out, &diag); code != 0 || calls != 1 {
				t.Fatalf("code=%d calls=%d %s", code, calls, &diag)
			}
		})
	}
}

func TestSentRejectsInvalidFlagsWithoutRequest(t *testing.T) {
	for _, args := range [][]string{{}, {"--mailbox", "liminal", "--limit", "51"}, {"--mailbox", "liminal", "--cursor", "a", "--id", "b"}, {"--mailbox", "liminal", "extra"}} {
		calls := 0
		setup(t, func(w http.ResponseWriter, r *http.Request) { calls++ })
		var out, diag bytes.Buffer
		if code := Run(append([]string{"email", "sent"}, args...), strings.NewReader(""), &out, &diag); code == 0 || calls != 0 {
			t.Fatalf("code=%d calls=%d", code, calls)
		}
	}
}

package fmg

import (
	"bytes"
	"net/http"
	"strings"
	"testing"
)

func TestInboxReadCommands(t *testing.T) {
	for _, mailbox := range []string{"liminal", "second"} {
		for _, extra := range [][]string{{}, {"--cursor", "abc:7:20"}, {"--id", "abc:7:41"}} {
			t.Run(mailbox+strings.Join(extra, " "), func(t *testing.T) {
				calls := 0
				setup(t, func(w http.ResponseWriter, r *http.Request) {
					calls++
					if r.Method != "GET" || r.URL.Path != "/v1/email/inbox" || r.URL.Query().Get("mailbox_id") != mailbox {
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
				args := append([]string{"email", "inbox", "--mailbox", mailbox}, extra...)
				if code := Run(args, strings.NewReader(""), &out, &diag); code != 0 || calls != 1 {
					t.Fatalf("code=%d calls=%d %s", code, calls, &diag)
				}
			})
		}
	}
}

func TestInboxRejectsInvalidFlagsWithoutRequest(t *testing.T) {
	for _, args := range [][]string{{}, {"--mailbox", "liminal", "--limit", "51"}, {"--mailbox", "liminal", "--cursor", "a", "--id", "b"}, {"--mailbox", "liminal", "extra"}} {
		calls := 0
		setup(t, func(w http.ResponseWriter, r *http.Request) { calls++ })
		var out, diag bytes.Buffer
		if code := Run(append([]string{"email", "inbox"}, args...), strings.NewReader(""), &out, &diag); code == 0 || calls != 0 {
			t.Fatalf("code=%d calls=%d", code, calls)
		}
	}
}

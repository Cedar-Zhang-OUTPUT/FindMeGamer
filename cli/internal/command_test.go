package fmg

import (
	"bytes"
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func setup(t *testing.T, handler http.HandlerFunc) (*httptest.Server, string) {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	path := filepath.Join(t.TempDir(), "config.json")
	t.Setenv("FMG_CONFIG", path)
	b, _ := json.Marshal(map[string]string{"server": server.URL, "token": "test-access-token"})
	if err := os.WriteFile(path, b, 0600); err != nil {
		t.Fatal(err)
	}
	return server, path
}

func TestUnknownCommand(t *testing.T) {
	var out, err bytes.Buffer
	if code := Run([]string{"unknown"}, strings.NewReader(""), &out, &err); code != 2 {
		t.Fatalf("exit=%d", code)
	}
}

func TestAuthCheckWithoutLoginUsesIdentityExit(t *testing.T) {
	t.Setenv("FMG_CONFIG", filepath.Join(t.TempDir(), "missing.json"))
	var out, err bytes.Buffer
	code := Run([]string{"auth", "check"}, strings.NewReader(""), &out, &err)
	if code != 3 {
		t.Fatalf("exit=%d stderr=%s", code, err.String())
	}
}

type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(r *http.Request) (*http.Response, error) { return f(r) }

type cancelOnRead struct{ cancel context.CancelFunc }

func (r cancelOnRead) Read(p []byte) (int, error) { r.cancel(); return 0, context.Canceled }
func (r cancelOnRead) Close() error               { return nil }

func TestCancellationWhileReadingBodyUsesCancelExit(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	client := newClient(Config{Server: "https://example.com", Token: "test-token"})
	client.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: cancelOnRead{cancel: cancel}, Request: r}, nil
	})
	_, err := client.request(ctx, http.MethodGet, "/v1/auth/check", nil)
	var diagnostics bytes.Buffer
	if code := writeError(&diagnostics, err); code != 130 {
		t.Fatalf("exit=%d %s", code, diagnostics.String())
	}
}

func TestSinglePagePreservesAllFields(t *testing.T) {
	count := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		count++
		if r.Header.Get("Authorization") != "Bearer test-access-token" {
			t.Error("missing access token")
		}
		if r.URL.Path != "/v1/providers/youtube/call" {
			t.Errorf("path=%s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"data":{"items":[],"unexpected":{"retained":true}},"meta":{"next_cursor":"p2"}}`))
	})
	var out, err bytes.Buffer
	code := Run([]string{"youtube", "call", "search.list", "--params", `{"part":"snippet"}`}, strings.NewReader(""), &out, &err)
	if code != 0 {
		t.Fatalf("exit=%d err=%s", code, err.String())
	}
	if count != 1 {
		t.Fatalf("requests=%d", count)
	}
	if !strings.Contains(out.String(), `"retained":true`) {
		t.Fatal(out.String())
	}
	if strings.Contains(out.String()+err.String(), "test-access-token") {
		t.Fatal("token leaked")
	}
}

func TestBoundedPagination(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(r.URL.Path, "/operations/") {
			w.Write([]byte(`{"data":{"pagination":{"request_param":"pageToken","items_path":["items"]}}}`))
			return
		}
		calls++
		var body struct {
			Params map[string]any `json:"params"`
		}
		json.NewDecoder(r.Body).Decode(&body)
		if calls == 2 && body.Params["pageToken"] != "p2" {
			t.Error("cursor lost")
		}
		w.Write([]byte(`{"data":{"items":[{"id":"a"}]},"meta":{"next_cursor":"p2"}}`))
	})
	var out, err bytes.Buffer
	code := Run([]string{"youtube", "call", "search.list", "--params", `{"part":"snippet"}`, "--max-pages", "2"}, strings.NewReader(""), &out, &err)
	if code != 0 || calls != 2 {
		t.Fatalf("code=%d calls=%d err=%s", code, calls, err.String())
	}
	if len(strings.Split(strings.TrimSpace(out.String()), "\n")) != 2 {
		t.Fatal(out.String())
	}
}

func TestItemLimitStopsAtCompletedPage(t *testing.T) {
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(r.URL.Path, "/operations/") {
			w.Write([]byte(`{"data":{"pagination":{"request_param":"pageToken","items_path":["items"]}}}`))
			return
		}
		calls++
		w.Write([]byte(`{"data":{"items":[1,2]},"meta":{"next_cursor":"p2"}}`))
	})
	var out, err bytes.Buffer
	code := Run([]string{"youtube", "call", "search.list", "--params", `{"part":"snippet"}`, "--max-pages", "5", "--max-items", "1"}, strings.NewReader(""), &out, &err)
	if code != 0 || calls != 1 {
		t.Fatalf("code=%d calls=%d", code, calls)
	}
	if !strings.Contains(out.String(), `[1,2]`) {
		t.Fatal("must retain whole page")
	}
}

func TestAuthFailureIsNonzeroWithoutLeakingToken(t *testing.T) {
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(401)
		w.Write([]byte(`{"error":{"code":"invalid_access_token","message":"Token revoked"}}`))
	})
	var out, err bytes.Buffer
	code := Run([]string{"x", "operations"}, strings.NewReader(""), &out, &err)
	if code != 3 || out.Len() != 0 {
		t.Fatalf("code=%d out=%s", code, out.String())
	}
	if strings.Contains(err.String(), "test-access-token") {
		t.Fatal("token leaked")
	}
}

func TestLoginVerifiesAndStoresPrivateConfig(t *testing.T) {
	server, path := setup(t, func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/v1/auth/check" || r.Header.Get("Authorization") != "Bearer new-token" {
			t.Error("wrong auth verification")
		}
		w.Write([]byte(`{"data":{"token_id":"id-1"}}`))
	})
	var out, err bytes.Buffer
	code := Run([]string{"auth", "login", "--server", server.URL, "--token-stdin"}, strings.NewReader("new-token\n"), &out, &err)
	if code != 0 {
		t.Fatalf("exit=%d %s", code, err.String())
	}
	info, e := os.Stat(path)
	if e != nil {
		t.Fatal(e)
	}
	if info.Mode().Perm() != 0600 {
		t.Fatalf("mode=%v", info.Mode())
	}
	if strings.Contains(out.String()+err.String(), "new-token") {
		t.Fatal("token leaked")
	}
	contents, _ := os.ReadFile(path)
	if !bytes.Contains(contents, []byte("new-token")) {
		t.Fatal("config not saved")
	}
}

func TestFailedLoginPreservesExistingConfig(t *testing.T) {
	server, path := setup(t, func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(401)
		w.Write([]byte(`{"error":{"code":"invalid_access_token"}}`))
	})
	before, _ := os.ReadFile(path)
	var out, err bytes.Buffer
	if Run([]string{"auth", "login", "--server", server.URL, "--token-stdin"}, strings.NewReader("bad-token\n"), &out, &err) != 3 {
		t.Fatal("expected unauthorized")
	}
	after, _ := os.ReadFile(path)
	if !bytes.Equal(before, after) {
		t.Fatal("failed login overwrote good config")
	}
}

func TestRemoteHTTPRejected(t *testing.T) {
	var out, err bytes.Buffer
	code := Run([]string{"auth", "login", "--server", "http://example.com", "--token-stdin"}, strings.NewReader("secret\n"), &out, &err)
	if code != 2 {
		t.Fatalf("code=%d", code)
	}
	if strings.Contains(err.String(), "secret") {
		t.Fatal("token leaked")
	}
}

func TestRedirectNotFollowed(t *testing.T) {
	redirected := 0
	target := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { redirected++ }))
	defer target.Close()
	setup(t, func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, target.URL, 302) })
	var out, err bytes.Buffer
	code := Run([]string{"x", "operations"}, strings.NewReader(""), &out, &err)
	if code == 0 || redirected != 0 {
		t.Fatalf("exit=%d redirects=%d", code, redirected)
	}
}

func TestCancellationRetainsCompletedPages(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	calls := 0
	setup(t, func(w http.ResponseWriter, r *http.Request) {
		if strings.Contains(r.URL.Path, "/operations/") {
			w.Write([]byte(`{"data":{"pagination":{"request_param":"pageToken","items_path":["items"]}}}`))
			return
		}
		calls++
		if calls == 2 {
			cancel()
			return
		}
		w.Write([]byte(`{"data":{"items":[1]},"meta":{"next_cursor":"p2"}}`))
	})
	var out, err bytes.Buffer
	code := RunContext(ctx, []string{"youtube", "call", "search.list", "--params", `{"part":"snippet"}`, "--max-pages", "4"}, strings.NewReader(""), &out, &err)
	if code != 130 {
		t.Fatalf("exit=%d", code)
	}
	if !strings.Contains(out.String(), `"items":[1]`) {
		t.Fatal("completed results lost")
	}
}

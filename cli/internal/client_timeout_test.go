package fmg

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type failedBody struct{ err error }

func TestTransportRecoveryDistinguishesReadsFromWritesWithoutReplaying(t *testing.T) {
	for _, method := range []string{http.MethodGet, http.MethodPost} {
		for _, code := range []string{"connection_failed", "request_timeout", "response_incomplete"} {
			t.Run(method+"/"+code, func(t *testing.T) {
				client := newClient(Config{Server: "https://example.com", Token: "private-token"})
				calls := 0
				client.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
					calls++
					if code == "request_timeout" {
						return nil, context.DeadlineExceeded
					}
					if code == "connection_failed" {
						return nil, errors.New("private-token network failure")
					}
					return &http.Response{StatusCode: 200, Header: make(http.Header), Body: failedBody{io.ErrUnexpectedEOF}, Request: r}, nil
				})
				_, err := client.request(context.Background(), method, "/v1/email/jobs/job1", nil)
				var api *APIError
				if !errors.As(err, &api) || api.Code != code || calls != 1 {
					t.Fatalf("%v calls=%d", err, calls)
				}
				raw, _ := json.Marshal(api)
				var fields map[string]any
				json.Unmarshal(raw, &fields)
				want := "retry_read"
				if method == http.MethodPost {
					want = "reconcile_write"
				}
				if fields["recovery"] != want || strings.Contains(string(raw), "private-token") {
					t.Fatalf("unsafe recovery: %s", raw)
				}
			})
		}
	}
}

func (b failedBody) Read([]byte) (int, error) { return 0, b.err }
func (b failedBody) Close() error             { return nil }

func TestTimeoutIsDistinctBeforeAndDuringBodyRead(t *testing.T) {
	for _, body := range []bool{false, true} {
		t.Run(map[bool]string{false: "headers", true: "body"}[body], func(t *testing.T) {
			client := newClient(Config{Server: "https://example.com", Token: "private-token"})
			client.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
				if !body {
					return nil, context.DeadlineExceeded
				}
				return &http.Response{StatusCode: 200, Header: make(http.Header), Body: failedBody{context.DeadlineExceeded}, Request: r}, nil
			})
			_, err := client.request(context.Background(), http.MethodGet, "/v1/outreach/tasks/task1", nil)
			var api *APIError
			if !errors.As(err, &api) || api.Code != "request_timeout" || !api.Retryable {
				t.Fatalf("expected explicit retryable timeout, got %#v", err)
			}
		})
	}
}

func TestBrokenBodyIsNotReportedAsTooLarge(t *testing.T) {
	client := newClient(Config{Server: "https://example.com", Token: "private-token"})
	client.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: failedBody{io.ErrUnexpectedEOF}, Request: r}, nil
	})
	_, err := client.request(context.Background(), http.MethodGet, "/v1/outreach/tasks/task1", nil)
	var api *APIError
	if !errors.As(err, &api) || api.Code != "response_incomplete" || !api.Retryable {
		t.Fatalf("got %#v", err)
	}
}

func TestRealBodyTimeoutDoesNotRetryOrMutate(t *testing.T) {
	calls := 0
	server, _ := setup(t, func(w http.ResponseWriter, r *http.Request) {
		calls++
		w.Write([]byte(`{"data":`))
		w.(http.Flusher).Flush()
		<-r.Context().Done()
	})
	client := newClient(Config{Server: server.URL, Token: "test-token"})
	client.http.Timeout = 20 * time.Millisecond
	_, err := client.request(context.Background(), http.MethodGet, "/v1/outreach/tasks/task1", nil)
	var diagnostics bytes.Buffer
	if code := writeError(&diagnostics, err); code != 5 {
		t.Fatal(code)
	}
	var api *APIError
	if !errors.As(err, &api) || api.Code != "request_timeout" || calls != 1 {
		t.Fatalf("error=%#v calls=%d", err, calls)
	}
}

func TestOversizedResponseHasItsOwnError(t *testing.T) {
	client := newClient(Config{Server: "https://example.com", Token: "private-token"})
	client.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
		return &http.Response{StatusCode: 200, Header: make(http.Header), Body: io.NopCloser(strings.NewReader(strings.Repeat("x", 32*1024*1024+1))), Request: r}, nil
	})
	_, err := client.request(context.Background(), http.MethodGet, "/v1/outreach/tasks/task1", nil)
	var api *APIError
	if !errors.As(err, &api) || api.Code != "response_too_large" || api.Retryable {
		t.Fatalf("got %#v", err)
	}
}

func TestRejectedHTTPWithBrokenBodyIsNotTransportRetry(t *testing.T) {
	for _, status := range []int{401, 403, 402, 429, 503} {
		for _, failure := range []error{io.ErrUnexpectedEOF, context.DeadlineExceeded} {
			client := newClient(Config{Server: "https://example.com", Token: "private-token"})
			client.http.Transport = roundTripFunc(func(r *http.Request) (*http.Response, error) {
				return &http.Response{StatusCode: status, Header: make(http.Header), Body: failedBody{failure}, Request: r}, nil
			})
			_, err := client.request(context.Background(), http.MethodGet, "/v1/email/jobs/job1", nil)
			var api *APIError
			if !errors.As(err, &api) || api.HTTPStatus != status || api.Recovery != "" || api.Retryable {
				t.Fatalf("status %d, failure %v: %#v", status, failure, api)
			}
		}
	}
}

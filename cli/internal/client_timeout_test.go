package fmg

import (
	"bytes"
	"context"
	"errors"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
)

type failedBody struct{ err error }

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

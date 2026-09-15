package fmg

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strings"
	"time"
)

type Response struct {
	Data json.RawMessage `json:"data"`
	Meta map[string]any  `json:"meta"`
}

type APIError struct {
	Code       string `json:"code"`
	Message    string `json:"message"`
	Retryable  bool   `json:"retryable"`
	RetryAfter *int   `json:"retry_after_seconds,omitempty"`
	Exit       int    `json:"-"`
}

func (e *APIError) Error() string { return e.Message }

type Client struct {
	config Config
	http   *http.Client
}

func newClient(config Config) *Client {
	return &Client{config: config, http: &http.Client{Timeout: 30 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error { return http.ErrUseLastResponse }}}
}

func (c *Client) request(ctx context.Context, method, path string, body any) (Response, error) {
	return c.requestWithKey(ctx, method, path, body, "")
}

func (c *Client) requestWithKey(ctx context.Context, method, path string, body any, key string) (Response, error) {
	var result Response
	var data []byte
	var err error
	if body != nil {
		data, err = json.Marshal(body)
		if err != nil {
			return result, err
		}
	}
	req, err := http.NewRequestWithContext(ctx, method, strings.TrimRight(c.config.Server, "/")+path, bytes.NewReader(data))
	if err != nil {
		return result, &APIError{Code: "invalid_configuration", Message: "Invalid service URL.", Exit: 2}
	}
	req.Header.Set("Authorization", "Bearer "+c.config.Token)
	req.Header.Set("Accept", "application/json")
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	response, err := c.http.Do(req)
	if err != nil {
		if errors.Is(ctx.Err(), context.Canceled) {
			return result, &APIError{Code: "cancelled", Message: "Cancelled; previously emitted pages are retained.", Exit: 130}
		}
		return result, &APIError{Code: "connection_failed", Message: "Could not reach the service; check address, connection and proxy.", Retryable: true, Exit: 5}
	}
	defer response.Body.Close()
	data, err = io.ReadAll(io.LimitReader(response.Body, 32*1024*1024+1))
	if err != nil || len(data) > 32*1024*1024 {
		if errors.Is(ctx.Err(), context.Canceled) {
			return result, &APIError{Code: "cancelled", Message: "Cancelled; previously emitted pages are retained.", Exit: 130}
		}
		return result, &APIError{Code: "invalid_response", Message: "Service response was incomplete or too large.", Exit: 5}
	}
	if response.StatusCode >= 300 {
		var envelope struct {
			Error APIError `json:"error"`
		}
		json.Unmarshal(data, &envelope)
		e := envelope.Error
		if e.Code == "" {
			e.Code = "service_error"
		}
		if e.Message == "" {
			e.Message = "Service rejected the request."
		}
		e.Message = strings.ReplaceAll(e.Message, c.config.Token, "[REDACTED]")
		e.Exit = 5
		switch response.StatusCode {
		case 400, 404, 422:
			e.Exit = 2
		case 401, 403:
			e.Exit = 3
		case 402, 429:
			e.Exit = 4
		}
		return result, &e
	}
	if json.Unmarshal(data, &result) != nil || len(result.Data) == 0 {
		return result, &APIError{Code: "invalid_response", Message: "Service did not return the expected JSON envelope.", Exit: 5}
	}
	return result, nil
}

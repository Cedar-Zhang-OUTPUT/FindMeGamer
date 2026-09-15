package fmg

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/url"
)

type Pagination struct {
	RequestParam string   `json:"request_param"`
	ItemsPath    []string `json:"items_path"`
}

func itemCount(data json.RawMessage, path []string) int {
	var node any
	if json.Unmarshal(data, &node) != nil {
		return 0
	}
	for _, part := range path {
		m, ok := node.(map[string]any)
		if !ok {
			return 0
		}
		node = m[part]
	}
	items, _ := node.([]any)
	return len(items)
}

func callPages(ctx context.Context, c *Client, provider, operation string, params map[string]any, maxPages, maxItems int, out io.Writer) error {
	var descriptor struct {
		Pagination *Pagination `json:"pagination"`
	}
	if maxPages > 1 || maxItems > 0 {
		desc, err := c.request(ctx, http.MethodGet, "/v1/providers/"+provider+"/operations/"+url.PathEscape(operation), nil)
		if err != nil {
			return err
		}
		if err = json.Unmarshal(desc.Data, &descriptor); err != nil {
			return errors.New("cannot decode pagination descriptor")
		}
	}
	count := 0
	seen := map[string]bool{}
	for page := 0; page < maxPages; page++ {
		response, err := c.request(ctx, http.MethodPost, "/v1/providers/"+provider+"/call", map[string]any{"operation": operation, "params": params})
		if err != nil {
			return err
		}
		if err = emit(out, response); err != nil {
			return &APIError{Code: "output_failed", Message: "Could not write results.", Exit: 5}
		}
		if descriptor.Pagination == nil || page+1 == maxPages {
			return nil
		}
		count += itemCount(response.Data, descriptor.Pagination.ItemsPath)
		if maxItems > 0 && count >= maxItems {
			return nil
		}
		cursor, ok := response.Meta["next_cursor"].(string)
		if !ok || cursor == "" {
			return nil
		}
		if seen[cursor] {
			return &APIError{Code: "repeated_cursor", Message: "Pagination stopped because the service repeated a cursor; emitted pages are retained.", Exit: 5}
		}
		seen[cursor] = true
		params[descriptor.Pagination.RequestParam] = cursor
	}
	return nil
}

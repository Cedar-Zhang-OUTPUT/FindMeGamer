package fmg

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
)

func runEmailSending(ctx context.Context, client *Client, args []string, out, diagnostics io.Writer) int {
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	switch args[0] {
	case "preview":
		input := flags.String("input", "", "JSON file containing template, recipient and variables")
		id := flags.String("id", "", "read an existing immutable preview")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || (*input == "") == (*id == "") {
			return writeError(diagnostics, errors.New("preview requires exactly one of --input FILE or --id ID"))
		}
		method, path := http.MethodGet, "/v1/email/previews/"+url.PathEscape(*id)
		var body map[string]any
		if *input != "" {
			file, err := os.Open(*input)
			if err != nil {
				return writeError(diagnostics, errors.New("cannot open preview input"))
			}
			raw, err := io.ReadAll(io.LimitReader(file, 1024*1024+1))
			file.Close()
			if err != nil || len(raw) > 1024*1024 {
				return writeError(diagnostics, errors.New("preview input is unreadable or larger than 1 MiB"))
			}
			decoder := json.NewDecoder(bytes.NewReader(raw))
			decoder.UseNumber()
			var trailing any
			if decoder.Decode(&body) != nil || body == nil || decoder.Decode(&trailing) != io.EOF {
				return writeError(diagnostics, errors.New("preview input must be one JSON object"))
			}
			method, path = http.MethodPost, "/v1/email/previews"
		}
		response, err := client.request(ctx, method, path, body)
		if err != nil {
			return writeError(diagnostics, err)
		}
		return emitEmail(out, diagnostics, response)
	case "send":
		id := flags.String("preview-id", "", "confirmed immutable preview")
		key := flags.String("idempotency-key", "", "stable key for this send")
		confirm := flags.Bool("confirm", false, "confirm the already reviewed recipient and content")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || *id == "" || strings.TrimSpace(*key) == "" || !*confirm {
			return writeError(diagnostics, errors.New("send requires --preview-id ID --confirm --idempotency-key KEY"))
		}
		response, err := client.requestWithKey(ctx, http.MethodPost, "/v1/email/sends", map[string]any{"preview_id": *id, "confirm": true}, *key)
		if err != nil {
			return writeError(diagnostics, err)
		}
		return emitReceipt(out, diagnostics, response)
	case "receipt":
		if len(args) != 2 || args[1] == "" || strings.ContainsAny(args[1], "/?#") {
			return writeError(diagnostics, errors.New("receipt requires one send ID"))
		}
		response, err := client.request(ctx, http.MethodGet, "/v1/email/sends/"+url.PathEscape(args[1]), nil)
		if err != nil {
			return writeError(diagnostics, err)
		}
		return emitReceipt(out, diagnostics, response)
	}
	return 2
}

func emitReceipt(out, diagnostics io.Writer, response Response) int {
	if code := emitEmail(out, diagnostics, response); code != 0 {
		return code
	}
	var receipt struct {
		State string `json:"state"`
	}
	if json.Unmarshal(response.Data, &receipt) != nil {
		return writeError(diagnostics, &APIError{Code: "invalid_response", Message: "Invalid send receipt.", Exit: 5})
	}
	switch receipt.State {
	case "sent", "sending", "queued":
		return 0
	case "failed":
		return writeError(diagnostics, &APIError{Code: "send_failed", Message: "SMTP explicitly failed; inspect the receipt. No automatic retry was performed.", Exit: 6})
	case "unknown":
		return writeError(diagnostics, &APIError{Code: "send_unknown", Message: "Delivery may already have occurred. Do not resend automatically.", Exit: 7})
	default:
		return writeError(diagnostics, &APIError{Code: "invalid_response", Message: "Unknown send receipt state.", Exit: 5})
	}
}

package fmg

import (
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

func runOutreach(ctx context.Context, args []string, out, diagnostics io.Writer) int {
	if len(args) < 2 || args[0] != "task" {
		return writeError(diagnostics, errors.New("use outreach task create|get|list|start"))
	}
	method, path := http.MethodGet, "/v1/outreach/tasks"
	var body any
	key := ""
	switch args[1] {
	case "list":
		if len(args) != 2 {
			return writeError(diagnostics, errors.New("list takes no arguments"))
		}
	case "get":
		if len(args) != 3 || args[2] == "" || strings.ContainsAny(args[2], "/?#") {
			return writeError(diagnostics, errors.New("get requires a task ID"))
		}
		path += "/" + url.PathEscape(args[2])
	case "create":
		flags := flag.NewFlagSet("create", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		input := flags.String("input", "", "batch JSON file")
		idempotency := flags.String("idempotency-key", "", "stable task creation key")
		if flags.Parse(args[2:]) != nil || flags.NArg() != 0 || *input == "" || strings.TrimSpace(*idempotency) == "" {
			return writeError(diagnostics, errors.New("create requires --input FILE --idempotency-key KEY"))
		}
		f, err := os.Open(*input)
		if err != nil {
			return writeError(diagnostics, errors.New("cannot open task input"))
		}
		defer f.Close()
		raw, err := io.ReadAll(io.LimitReader(f, 8*1024*1024+1))
		var object map[string]any
		if err != nil || len(raw) > 8*1024*1024 || json.Unmarshal(raw, &object) != nil || object == nil {
			return writeError(diagnostics, errors.New("task input must be a JSON object up to 8 MiB"))
		}
		body, key, method = object, *idempotency, http.MethodPost
	case "start":
		if len(args) < 3 || args[2] == "" || strings.ContainsAny(args[2], "/?#") {
			return writeError(diagnostics, errors.New("start requires a task ID"))
		}
		flags := flag.NewFlagSet("start", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		revision := flags.String("revision", "", "reviewed task revision")
		confirm := flags.Bool("confirm", false, "user approved every recipient and draft")
		if flags.Parse(args[3:]) != nil || flags.NArg() != 0 || *revision == "" || !*confirm {
			return writeError(diagnostics, errors.New("start requires --revision REVISION --confirm"))
		}
		method, path, body = http.MethodPost, path+"/"+url.PathEscape(args[2])+"/start", map[string]any{"revision": *revision, "confirm": true}
	default:
		return writeError(diagnostics, errors.New("unknown outreach task command"))
	}
	config, err := loadConfig()
	if err != nil {
		return writeError(diagnostics, &APIError{Code: "login_required", Message: err.Error(), Exit: 3})
	}
	response, err := newClient(config).requestWithKey(ctx, method, path, body, key)
	if err != nil {
		return writeError(diagnostics, err)
	}
	return emitEmail(out, diagnostics, response)
}

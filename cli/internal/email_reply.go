package fmg

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
)

func runEmailReply(ctx context.Context, client *Client, args []string, out, diagnostics io.Writer) int {
	flags := flag.NewFlagSet(args[0], flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	method, path := http.MethodGet, ""
	var body map[string]any
	switch args[0] {
	case "reply":
		if len(args) != 2 || args[1] == "" || strings.ContainsAny(args[1], "/?#") {
			return writeError(diagnostics, errors.New("reply requires one server reply ID"))
		}
		path = "/v1/email/replies/" + url.PathEscape(args[1])
	case "reply-history":
		task := flags.String("task-id", "", "original outreach task")
		creator := flags.String("creator-id", "", "optional creator within the task")
		limit := flags.Int("limit", 10, "page size, 1 to 20")
		cursor := flags.String("cursor", "", "next_cursor from the last page")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || *task == "" || *limit < 1 || *limit > 20 {
			return writeError(diagnostics, errors.New("reply-history requires --task-id ID and limit 1 to 20"))
		}
		q := url.Values{"task_id": {*task}, "limit": {strconv.Itoa(*limit)}}
		if *creator != "" {
			q.Set("creator_id", *creator)
		}
		if *cursor != "" {
			q.Set("cursor", *cursor)
		}
		path = "/v1/email/reply-history?" + q.Encode()
	case "reply-preview":
		input := flags.String("input", "", "JSON variables or explicitly confirmed custom text")
		id := flags.String("reply-id", "", "server reply ID")
		selection := draftSelectionFlags(flags)
		recipient := flags.String("recipient-mode", "", "sender (default) or explicitly selected reply_to")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || *input == "" {
			return writeError(diagnostics, errors.New("reply-preview requires --input FILE and explicit reply/mailbox selection"))
		}
		file, err := os.Open(*input)
		if err != nil {
			return writeError(diagnostics, errors.New("cannot open reply input"))
		}
		raw, err := io.ReadAll(io.LimitReader(file, 1024*1024+1))
		file.Close()
		if err != nil || len(raw) > 1024*1024 {
			return writeError(diagnostics, errors.New("reply input is unreadable or larger than 1 MiB"))
		}
		decoder := json.NewDecoder(bytes.NewReader(raw))
		decoder.UseNumber()
		var trailing any
		if decoder.Decode(&body) != nil || body == nil || decoder.Decode(&trailing) != io.EOF {
			return writeError(diagnostics, errors.New("reply input must be one JSON object"))
		}
		merge := func(key, value string, required bool) error {
			if value != "" {
				if old, ok := body[key]; ok && old != value {
					return fmt.Errorf("flag conflicts with JSON %s", key)
				}
				body[key] = value
			}
			if required {
				text, ok := body[key].(string)
				if !ok || strings.TrimSpace(text) == "" {
					return fmt.Errorf("explicit %s is required", key)
				}
			}
			return nil
		}
		if err := merge("reply_id", *id, true); err != nil {
			return writeError(diagnostics, err)
		}
		if _, custom := body["text"]; custom {
			if *selection.template != "" || *selection.version != "" {
				return writeError(diagnostics, errors.New("custom text cannot use template flags"))
			}
			if err := merge("mailbox_id", *selection.mailbox, true); err != nil {
				return writeError(diagnostics, err)
			}
			if body["text_confirmed"] != true {
				return writeError(diagnostics, errors.New("custom text requires text_confirmed=true after user review"))
			}
		} else if err := selection.merge(flags, body); err != nil {
			return writeError(diagnostics, err)
		}
		if err := merge("recipient_mode", *recipient, false); err != nil {
			return writeError(diagnostics, err)
		}
		method, path = http.MethodPost, "/v1/email/reply-previews"
	}
	response, err := client.request(ctx, method, path, body)
	if err != nil {
		return writeError(diagnostics, err)
	}
	return emitEmail(out, diagnostics, response)
}

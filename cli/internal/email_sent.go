package fmg

import (
	"context"
	"errors"
	"flag"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

func runEmailSent(ctx context.Context, client *Client, args []string, out, diagnostics io.Writer) int {
	flags := flag.NewFlagSet("sent", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	mailbox := flags.String("mailbox", "", "mailbox ID (required)")
	limit := flags.Int("limit", 20, "UID window size, 1–50")
	cursor := flags.String("cursor", "", "next_cursor from the preceding page")
	id := flags.String("id", "", "message ID from Sent listing")
	if flags.Parse(args) != nil || flags.NArg() != 0 || strings.TrimSpace(*mailbox) == "" || *limit < 1 || *limit > 50 || (*cursor != "" && *id != "") {
		return writeError(diagnostics, errors.New("sent requires --mailbox ID; use --limit 1–50, --cursor CURSOR or --id MESSAGE_ID"))
	}
	query := url.Values{"mailbox_id": {*mailbox}, "limit": {strconv.Itoa(*limit)}}
	if *cursor != "" {
		query.Set("cursor", *cursor)
	}
	if *id != "" {
		query.Set("message_id", *id)
	}
	response, err := client.request(ctx, http.MethodGet, "/v1/email/sent?"+query.Encode(), nil)
	if err != nil {
		return writeError(diagnostics, err)
	}
	return emitEmail(out, diagnostics, response)
}

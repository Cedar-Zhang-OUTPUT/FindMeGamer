package fmg

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"
)

var Version = "0.1.0-dev"

type runIDKey struct{}

const help = `fmg — company-hosted API tools

fmg auth login --server https://SERVICE --token-stdin
fmg auth check | logout
fmg youtube|x|steam operations
fmg youtube|x|steam describe OPERATION
fmg youtube|x|steam call OPERATION --params JSON [--max-pages N] [--max-items N]
fmg version
fmg --run-id RUN_ID usage
Prefix other commands with --run-id RUN_ID to attribute requests.
fmg email enrich --url URL --idempotency-key KEY [--name NAME] [--platform PLATFORM]
fmg email job ID [--wait] [--timeout 5m]
fmg email retry ID
fmg email templates
fmg email template TEMPLATE_ID
fmg email preview --input message.json | --id PREVIEW_ID
fmg email send --preview-id PREVIEW_ID --confirm --idempotency-key KEY
fmg email receipt SEND_ID

Default: one upstream page, JSON stdout, diagnostics stderr.
With --max-pages: NDJSON, one whole response envelope per page.
--max-items stops at page boundaries; the last page can exceed the count.
No automatic request retries. Ctrl-C retains emitted pages (exit 130).
Read tokens from stdin, never command arguments. Company provider keys stay on the server.
`

func Run(args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	return RunContext(context.Background(), args, stdin, stdout, stderr)
}

func RunContext(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) > 0 && args[0] == "--run-id" {
		if len(args) < 3 || args[1] == "" {
			return writeError(stderr, errors.New("--run-id requires an ID and command"))
		}
		ctx = context.WithValue(ctx, runIDKey{}, args[1])
		args = args[2:]
	}
	if len(args) == 0 || args[0] == "--help" || args[0] == "help" {
		fmt.Fprint(stdout, help)
		return 0
	}
	if args[0] == "version" || args[0] == "--version" {
		emit(stdout, map[string]string{"version": Version})
		return 0
	}
	if args[0] == "auth" {
		return runAuth(ctx, args[1:], stdin, stdout, stderr)
	}
	if args[0] == "email" {
		return runEmail(ctx, args[1:], stdout, stderr)
	}
	if args[0] == "usage" {
		id, _ := ctx.Value(runIDKey{}).(string)
		if len(args) != 1 || id == "" {
			return writeError(stderr, errors.New("use fmg --run-id ID usage"))
		}
		config, err := loadConfig()
		if err != nil {
			return writeError(stderr, &APIError{Code: "login_required", Message: err.Error(), Exit: 3})
		}
		result, err := newClient(config).request(ctx, http.MethodGet, "/v1/usage?run_id="+url.QueryEscape(id), nil)
		if err != nil {
			return writeError(stderr, err)
		}
		if err = emit(stdout, result); err != nil {
			return writeError(stderr, err)
		}
		return 0
	}
	provider := args[0]
	if provider != "youtube" && provider != "x" && provider != "steam" {
		return writeError(stderr, errors.New("unknown command; use fmg --help"))
	}
	if len(args) < 2 {
		return writeError(stderr, errors.New("choose operations, describe or call"))
	}
	config, err := loadConfig()
	if err != nil {
		return writeError(stderr, &APIError{Code: "login_required", Message: err.Error(), Exit: 3})
	}
	client := newClient(config)
	switch args[1] {
	case "operations":
		if len(args) != 2 {
			return writeError(stderr, errors.New("operations takes no arguments"))
		}
		response, e := client.request(ctx, http.MethodGet, "/v1/providers/"+provider+"/operations", nil)
		if e != nil {
			return writeError(stderr, e)
		}
		if e = emit(stdout, response); e != nil {
			return writeError(stderr, errors.New("could not write results"))
		}
		return 0
	case "describe":
		if len(args) != 3 {
			return writeError(stderr, errors.New("describe requires an operation ID"))
		}
		response, e := client.request(ctx, http.MethodGet, "/v1/providers/"+provider+"/operations/"+url.PathEscape(args[2]), nil)
		if e != nil {
			return writeError(stderr, e)
		}
		if e = emit(stdout, response); e != nil {
			return writeError(stderr, errors.New("could not write results"))
		}
		return 0
	case "call":
		if len(args) < 3 {
			return writeError(stderr, errors.New("call requires an operation ID"))
		}
		flags := flag.NewFlagSet("call", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		raw := flags.String("params", "{}", "JSON operation parameters")
		pages := flags.Int("max-pages", 1, "maximum complete pages")
		items := flags.Int("max-items", 0, "stop after a page reaches this item count")
		if flags.Parse(args[3:]) != nil || flags.NArg() != 0 || *pages < 1 || *items < 0 {
			return writeError(stderr, errors.New("invalid call options; use fmg --help"))
		}
		var params map[string]any
		decoder := json.NewDecoder(strings.NewReader(*raw))
		decoder.UseNumber()
		if decoder.Decode(&params) != nil || params == nil {
			return writeError(stderr, errors.New("--params must be a JSON object"))
		}
		var trailing any
		if decoder.Decode(&trailing) != io.EOF {
			return writeError(stderr, errors.New("--params must contain exactly one JSON object"))
		}
		if err = callPages(ctx, client, provider, args[2], params, *pages, *items, stdout); err != nil {
			return writeError(stderr, err)
		}
		return 0
	default:
		return writeError(stderr, errors.New("unknown provider command; use fmg --help"))
	}
}

func runAuth(ctx context.Context, args []string, stdin io.Reader, stdout, stderr io.Writer) int {
	if len(args) == 0 {
		return writeError(stderr, errors.New("choose auth login, check or logout"))
	}
	switch args[0] {
	case "login":
		flags := flag.NewFlagSet("login", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		server := flags.String("server", "", "company gateway URL")
		tokenStdin := flags.Bool("token-stdin", false, "read private access token from stdin")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || !*tokenStdin {
			return writeError(stderr, errors.New("login requires --server and --token-stdin"))
		}
		if err := validateServer(*server); err != nil {
			return writeError(stderr, err)
		}
		raw, err := io.ReadAll(io.LimitReader(stdin, 65537))
		if err != nil || len(raw) > 65536 {
			return writeError(stderr, errors.New("cannot read access token from stdin"))
		}
		token := strings.TrimSpace(string(raw))
		if token == "" || strings.ContainsAny(token, "\r\n\t ") {
			return writeError(stderr, errors.New("invalid access token input"))
		}
		config := Config{Server: strings.TrimRight(*server, "/"), Token: token}
		if _, err = newClient(config).request(ctx, http.MethodGet, "/v1/auth/check", nil); err != nil {
			return writeError(stderr, err)
		}
		if err = saveConfig(config); err != nil {
			return writeError(stderr, err)
		}
		emit(stdout, map[string]bool{"authenticated": true})
		return 0
	case "logout":
		if len(args) != 1 {
			return writeError(stderr, errors.New("logout takes no arguments"))
		}
		path, err := configPath()
		if err != nil {
			return writeError(stderr, err)
		}
		if err = os.Remove(path); err != nil && !os.IsNotExist(err) {
			return writeError(stderr, errors.New("cannot remove local configuration"))
		}
		emit(stdout, map[string]bool{"logged_out": true})
		return 0
	case "check":
		if len(args) != 1 {
			return writeError(stderr, errors.New("check takes no arguments"))
		}
		config, err := loadConfig()
		if err != nil {
			return writeError(stderr, &APIError{Code: "login_required", Message: err.Error(), Exit: 3})
		}
		result, err := newClient(config).request(ctx, http.MethodGet, "/v1/auth/check", nil)
		if err != nil {
			return writeError(stderr, err)
		}
		emit(stdout, result)
		return 0
	default:
		return writeError(stderr, errors.New("unknown auth command"))
	}
}

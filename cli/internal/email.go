package fmg

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

func runEmail(ctx context.Context, args []string, out, diagnostics io.Writer) int {
	if len(args) == 0 {
		return writeError(diagnostics, errors.New("choose enrich, job or retry"))
	}
	config, err := loadConfig()
	if err != nil {
		return writeError(diagnostics, &APIError{Code: "login_required", Message: err.Error(), Exit: 3})
	}
	client := newClient(config)
	if args[0] == "templates" || args[0] == "template" {
		path := "/v1/email/templates"
		if args[0] == "templates" && len(args) != 1 {
			return writeError(diagnostics, errors.New("templates takes no arguments"))
		}
		if args[0] == "template" {
			if len(args) != 2 || args[1] == "" || strings.ContainsAny(args[1], "/?#") {
				return writeError(diagnostics, errors.New("template requires one template ID"))
			}
			path += "/" + url.PathEscape(args[1])
		}
		response, e := client.request(ctx, http.MethodGet, path, nil)
		if e != nil {
			return writeError(diagnostics, e)
		}
		return emitEmail(out, diagnostics, response)
	}
	if args[0] == "enrich" {
		flags := flag.NewFlagSet("enrich", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		target := flags.String("url", "", "public creator URL")
		name := flags.String("name", "", "creator name")
		platform := flags.String("platform", "", "platform")
		key := flags.String("idempotency-key", "", "stable key for this logical request")
		if flags.Parse(args[1:]) != nil || flags.NArg() != 0 || *target == "" || strings.TrimSpace(*key) == "" {
			return writeError(diagnostics, errors.New("enrich requires --url and --idempotency-key"))
		}
		body := map[string]any{"url": *target}
		if *name != "" {
			body["name"] = *name
		}
		if *platform != "" {
			body["platform"] = *platform
		}
		response, e := client.requestWithKey(ctx, http.MethodPost, "/v1/email/enrich", body, *key)
		if e != nil {
			return writeError(diagnostics, e)
		}
		return emitEmail(out, diagnostics, response)
	}
	if len(args) < 2 || args[1] == "" || strings.ContainsAny(args[1], "/?#") {
		return writeError(diagnostics, errors.New("a job ID is required"))
	}
	path := "/v1/email/jobs/" + url.PathEscape(args[1])
	switch args[0] {
	case "retry":
		if len(args) != 2 {
			return writeError(diagnostics, errors.New("retry takes one job ID"))
		}
		response, e := client.request(ctx, http.MethodPost, path+"/retry", nil)
		if e != nil {
			return writeError(diagnostics, e)
		}
		return emitEmail(out, diagnostics, response)
	case "job":
		flags := flag.NewFlagSet("job", flag.ContinueOnError)
		flags.SetOutput(io.Discard)
		wait := flags.Bool("wait", false, "poll this job without re-executing it")
		timeout := flags.Duration("timeout", 5*time.Minute, "maximum polling duration")
		if flags.Parse(args[2:]) != nil || flags.NArg() != 0 || *timeout <= 0 {
			return writeError(diagnostics, errors.New("invalid job options"))
		}
		deadline := time.Now().Add(*timeout)
		for {
			response, e := client.request(ctx, http.MethodGet, path, nil)
			if e != nil {
				return writeError(diagnostics, e)
			}
			var job struct {
				State string `json:"state"`
			}
			if json.Unmarshal(response.Data, &job) != nil || job.State == "" {
				return writeError(diagnostics, &APIError{Code: "invalid_response", Message: "Missing job state.", Exit: 5})
			}
			if code := emitEmail(out, diagnostics, response); code != 0 {
				return code
			}
			if job.State == "failed" {
				return writeError(diagnostics, &APIError{Code: "job_failed", Message: "Job failed; inspect the result before explicitly retrying.", Exit: 6})
			}
			if !*wait || job.State == "completed" {
				return 0
			}
			remaining := time.Until(deadline)
			if remaining <= 0 {
				return writeError(diagnostics, &APIError{Code: "wait_timeout", Message: "Stopped waiting; the server job continues. Query the same ID later.", Exit: 5})
			}
			delay := min(2*time.Second, remaining)
			timer := time.NewTimer(delay)
			select {
			case <-ctx.Done():
				timer.Stop()
				return writeError(diagnostics, &APIError{Code: "cancelled", Message: "Stopped waiting; server work is not cancelled.", Exit: 130})
			case <-timer.C:
			}
		}
	default:
		return writeError(diagnostics, errors.New("unknown email command"))
	}
}

func emitEmail(out, diagnostics io.Writer, response Response) int {
	if emit(out, response) != nil {
		return writeError(diagnostics, &APIError{Code: "output_failed", Message: "Could not write result.", Exit: 5})
	}
	return 0
}

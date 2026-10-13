package fmg

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"net/url"
	"os"
	"strings"
	"unicode/utf8"
)

type contactEvidence struct {
	SourceURL string  `json:"source_url"`
	Text      *string `json:"text"`
	Kind      *string `json:"kind,omitempty"`
}

func readContactEvidence(path string) ([]contactEvidence, error) {
	invalid := errors.New("evidence requires a JSON array: max 10 records, public source_url and text (8000 characters each, 32000 total); file max 256000 bytes")
	file, err := os.Open(path)
	if err != nil {
		return nil, invalid
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, 256001))
	if err != nil || len(data) > 256000 || !utf8.Valid(data) {
		return nil, invalid
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	var records []contactEvidence
	if decoder.Decode(&records) != nil || records == nil || len(records) > 10 {
		return nil, invalid
	}
	var extra any
	if decoder.Decode(&extra) != io.EOF {
		return nil, invalid
	}
	total := 0
	for _, record := range records {
		if record.Text == nil || utf8.RuneCountInString(*record.Text) > 8000 || len(record.SourceURL) > 4096 || (record.Kind != nil && utf8.RuneCountInString(*record.Kind) > 80) {
			return nil, invalid
		}
		total += utf8.RuneCountInString(*record.Text)
		source, err := url.Parse(record.SourceURL)
		if err != nil || (source.Scheme != "https" && source.Scheme != "http") || source.Hostname() == "" || source.User != nil || (source.Port() != "" && source.Port() != "80" && source.Port() != "443") || strings.ContainsAny(record.SourceURL, "\\ \t\r\n") {
			return nil, invalid
		}
		host := strings.ToLower(strings.TrimSuffix(source.Hostname(), "."))
		ip := net.ParseIP(host)
		if host == "localhost" || strings.HasSuffix(host, ".localhost") || host == "metadata.google.internal" || (ip != nil && (!ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast())) {
			return nil, invalid
		}
	}
	if total > 32000 {
		return nil, invalid
	}
	return records, nil
}

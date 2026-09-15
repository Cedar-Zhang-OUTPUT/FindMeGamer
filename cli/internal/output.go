package fmg

import (
	"encoding/json"
	"errors"
	"io"
)

func writeError(w io.Writer, err error) int {
	var api *APIError
	if !errors.As(err, &api) {
		api = &APIError{Code: "invalid_request", Message: err.Error(), Exit: 2}
	}
	json.NewEncoder(w).Encode(map[string]any{"error": api})
	return api.Exit
}

func emit(w io.Writer, value any) error { return json.NewEncoder(w).Encode(value) }

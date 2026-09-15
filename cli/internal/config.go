package fmg

import (
	"encoding/json"
	"errors"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
)

type Config struct {
	Server string `json:"server"`
	Token  string `json:"token"`
}

func configPath() (string, error) {
	if path := os.Getenv("FMG_CONFIG"); path != "" {
		return path, nil
	}
	root, err := os.UserConfigDir()
	if err != nil {
		return "", errors.New("cannot locate private configuration directory")
	}
	return filepath.Join(root, "fmg", "config.json"), nil
}

func validateServer(server string) error {
	u, err := url.Parse(server)
	if err != nil || u.Hostname() == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" || strings.Contains(server, "\\") {
		return errors.New("invalid service URL")
	}
	loopback := strings.EqualFold(u.Hostname(), "localhost")
	if ip := net.ParseIP(u.Hostname()); ip != nil {
		loopback = ip.IsLoopback()
	}
	if u.Scheme != "https" && !(u.Scheme == "http" && loopback) {
		return errors.New("remote services require HTTPS")
	}
	return nil
}

func loadConfig() (Config, error) {
	var config Config
	path, err := configPath()
	if err != nil {
		return config, err
	}
	info, err := os.Stat(path)
	if err != nil {
		return config, errors.New("not logged in; run fmg auth login")
	}
	if info.Mode().Perm()&0077 != 0 {
		return config, errors.New("configuration must be private (chmod 600)")
	}
	contents, err := os.ReadFile(path)
	if err != nil || json.Unmarshal(contents, &config) != nil || config.Token == "" {
		return Config{}, errors.New("cannot read valid configuration")
	}
	if err = validateServer(config.Server); err != nil {
		return Config{}, err
	}
	return config, nil
}

func saveConfig(config Config) error {
	path, err := configPath()
	if err != nil {
		return err
	}
	if err = os.MkdirAll(filepath.Dir(path), 0700); err != nil {
		return errors.New("cannot create configuration directory")
	}
	file, err := os.CreateTemp(filepath.Dir(path), ".fmg-config-*")
	if err != nil {
		return errors.New("cannot create private configuration")
	}
	temporary := file.Name()
	defer os.Remove(temporary)
	if err = file.Chmod(0600); err == nil {
		err = json.NewEncoder(file).Encode(config)
	}
	if err == nil {
		err = file.Sync()
	}
	closeErr := file.Close()
	if err == nil {
		err = closeErr
	}
	if err == nil {
		err = os.Rename(temporary, path)
	}
	if err != nil {
		return errors.New("cannot save private configuration")
	}
	return nil
}

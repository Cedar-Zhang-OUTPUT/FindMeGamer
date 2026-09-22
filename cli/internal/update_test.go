package fmg

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestUpdateCacheReusesReleaseAndRefreshesInstalledVersions(t *testing.T) {
	path := filepath.Join(t.TempDir(), "updates.json")
	now := time.Now()
	fetch := func(context.Context) (string, error) { return "fmg-v0.10.0", nil }
	a := checkUpdates(context.Background(), path, "0.9.0", map[string]string{"fmg-api": "0.9.0"}, false, now, fetch)
	if !a.CLIUpdate || !a.SkillUpdate || a.Latest != "0.10.0" {
		t.Fatalf("%+v", a)
	}
	fail := func(context.Context) (string, error) { return "", errors.New("offline") }
	b := checkUpdates(context.Background(), path, "0.10.0", map[string]string{"fmg-api": "0.10.0"}, false, now.Add(time.Minute), fail)
	if b.Status != "current" || b.CLIUpdate || b.SkillUpdate {
		t.Fatalf("%+v", b)
	}
	c := checkUpdates(context.Background(), path, "0.10.0", nil, true, now, fail)
	if c.Status != "check_unavailable" {
		t.Fatalf("%+v", c)
	}
}

func TestUpdateExpiryAndMissingSkillsAreNotClaimedCurrent(t *testing.T) {
	path := filepath.Join(t.TempDir(), "updates.json")
	fetch := func(context.Context) (string, error) { return "fmg-v1.0.0", nil }
	a := checkUpdates(context.Background(), path, "1.0.0", map[string]string{"fmg-api": "unknown", "fmg-research": "0.9.0"}, false, time.Now(), fetch)
	if !a.SkillUpdate || a.Status != "update_available" {
		t.Fatalf("%+v", a)
	}
	b := checkUpdates(context.Background(), path, "1.0.0", map[string]string{"fmg-api": "unknown"}, false, time.Now(), fetch)
	if b.Status != "skill_version_unknown" {
		t.Fatalf("%+v", b)
	}
	c := checkUpdates(context.Background(), path, "1.0.0", nil, false, time.Now().Add(7*time.Hour), func(context.Context) (string, error) { return "", errors.New("offline") })
	if c.Status != "check_unavailable" {
		t.Fatalf("%+v", c)
	}
}

func TestAutomaticNoticeDoesNotCorruptPricingJSON(t *testing.T) {
	old := Version
	Version = "0.1.0"
	defer func() { Version = old }()
	dir := t.TempDir()
	t.Setenv("FMG_CONFIG", filepath.Join(dir, "config.json"))
	t.Setenv("FMG_SKILL_DIR", dir)
	if err := saveConfig(Config{Server: "https://example.com", Token: "never-log-me"}); err != nil {
		t.Fatal(err)
	}
	checkUpdates(context.Background(), filepath.Join(dir, "updates.json"), Version, nil, false, time.Now(), func(context.Context) (string, error) { return "fmg-v99.0.0", nil })
	var out, errs bytes.Buffer
	code := Run([]string{"pricing"}, strings.NewReader(""), &out, &errs)
	var notice struct {
		Update updateInfo `json:"update"`
	}
	parseErr := json.Unmarshal(errs.Bytes(), &notice)
	if code != 0 || parseErr != nil || notice.Update.Status != "update_available" || strings.Contains(out.String(), "update_available") || strings.Contains(errs.String(), "never-log-me") {
		t.Fatalf("%d %s %s", code, out.String(), errs.String())
	}
	if _, err := os.Stat(filepath.Join(dir, "fmg")); !os.IsNotExist(err) {
		t.Fatal("unexpected installation")
	}
}

func TestUpdateFailureIsCachedAndDoesNotRetryBusinessCommand(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("FMG_CONFIG", filepath.Join(dir, "config.json"))
	if err := saveConfig(Config{Server: "https://example.com", Token: "secret"}); err != nil {
		t.Fatal(err)
	}
	calls := 0
	fetch := func(context.Context) (string, error) { calls++; return "", errors.New("offline") }
	now := time.Now()
	path := filepath.Join(dir, "updates.json")
	checkUpdates(context.Background(), path, "0.1.0", nil, false, now, fetch)
	checkUpdates(context.Background(), path, "0.1.0", nil, false, now.Add(time.Minute), fetch)
	if calls != 1 {
		t.Fatalf("failed check was not cached: %d", calls)
	}
	var out, errs bytes.Buffer
	if code := Run([]string{"pricing"}, strings.NewReader(""), &out, &errs); code != 0 || !json.Valid(out.Bytes()) || errs.Len() != 0 {
		t.Fatalf("%d %s %s", code, out.String(), errs.String())
	}
}

func TestInstalledSkillVersionsRequireActualSkill(t *testing.T) {
	dir := t.TempDir()
	folder := filepath.Join(dir, "fmg-api")
	os.MkdirAll(folder, 0700)
	os.WriteFile(filepath.Join(folder, ".fmg-release.json"), []byte(`{"version":"0.7.0"}`), 0600)
	if installedSkillVersions(dir)["fmg-api"] != "unknown" {
		t.Fatal("missing Skill reported installed")
	}
	os.WriteFile(filepath.Join(folder, "SKILL.md"), []byte("instructions"), 0600)
	versions := installedSkillVersions(dir)
	if versions["fmg-api"] != "0.7.0" || versions["fmg-research"] != "unknown" {
		t.Fatal(versions)
	}
}

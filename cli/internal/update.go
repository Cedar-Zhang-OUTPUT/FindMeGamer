package fmg

import (
	"context"
	"encoding/json"
	"errors"
	"flag"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"
)

type updateInfo struct {
	Status      string            `json:"status"`
	Installed   string            `json:"installed_cli"`
	Latest      string            `json:"latest_version,omitempty"`
	Skills      map[string]string `json:"installed_skills"`
	CLIUpdate   bool              `json:"cli_update_available"`
	SkillUpdate bool              `json:"skill_update_available"`
	CheckedAt   time.Time         `json:"checked_at"`
	Command     string            `json:"upgrade_command"`
	Reload      string            `json:"after_upgrade"`
	ReleaseURL  string            `json:"release_url,omitempty"`
}
type updateCache struct {
	Tag       string    `json:"tag"`
	CheckedAt time.Time `json:"checked_at"`
}
type releaseLookup func(context.Context) (string, error)

func versionParts(value string) ([3]int, bool) {
	var parts [3]int
	match := regexp.MustCompile(`^(?:fmg-v)?([0-9]+)\.([0-9]+)\.([0-9]+)$`).FindStringSubmatch(value)
	if match == nil {
		return parts, false
	}
	for i := 0; i < 3; i++ {
		n, err := strconv.Atoi(match[i+1])
		if err != nil {
			return parts, false
		}
		parts[i] = n
	}
	return parts, true
}
func newer(latest, installed string) bool {
	a, ok := versionParts(latest)
	b, valid := versionParts(installed)
	if !ok || !valid {
		return false
	}
	for i := 0; i < 3; i++ {
		if a[i] != b[i] {
			return a[i] > b[i]
		}
	}
	return false
}
func writeUpdateCache(path string, cache updateCache) {
	if os.MkdirAll(filepath.Dir(path), 0700) != nil {
		return
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".updates-*")
	if err != nil {
		return
	}
	defer os.Remove(f.Name())
	err = json.NewEncoder(f).Encode(cache)
	closeErr := f.Close()
	if err == nil && closeErr == nil {
		_ = os.Rename(f.Name(), path)
	}
}
func checkUpdates(ctx context.Context, path, installed string, skills map[string]string, refresh bool, now time.Time, fetch releaseLookup) updateInfo {
	info := updateInfo{Status: "check_unavailable", Installed: installed, Skills: skills,
		Command: "fmg upgrade --latest --skills", Reload: "Verify fmg version; re-read both installed SKILL.md files and relevant references before continuing. Preserve existing task IDs; do not replay work."}
	var cache updateCache
	raw, _ := os.ReadFile(path)
	_ = json.Unmarshal(raw, &cache)
	ttl := 6 * time.Hour
	if cache.Tag == "" {
		ttl = 15 * time.Minute
	}
	age := now.Sub(cache.CheckedAt)
	if refresh || cache.CheckedAt.IsZero() || age < 0 || age >= ttl {
		tag, err := fetch(ctx)
		cache = updateCache{CheckedAt: now}
		if _, valid := versionParts(tag); err == nil && valid {
			cache.Tag = tag
		}
		writeUpdateCache(path, cache)
	}
	info.CheckedAt = cache.CheckedAt
	if _, ok := versionParts(cache.Tag); !ok {
		return info
	}
	info.Latest = strings.TrimPrefix(cache.Tag, "fmg-v")
	info.ReleaseURL = "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tag/fmg-v" + info.Latest
	info.CLIUpdate = newer(info.Latest, installed)
	unknown := len(skills) == 0
	for _, v := range skills {
		if _, ok := versionParts(v); !ok {
			unknown = true
		} else if newer(info.Latest, v) {
			info.SkillUpdate = true
		}
	}
	info.Status = "current"
	if unknown {
		info.Status = "skill_version_unknown"
	}
	if info.CLIUpdate || info.SkillUpdate {
		info.Status = "update_available"
	}
	return info
}

func publishedVersion(ctx context.Context) (string, error) {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, "https://api.github.com/repos/Cedar-Zhang-OUTPUT/FindMeGamer/releases?per_page=100", nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("User-Agent", "fmg-cli-update-check")
	client := &http.Client{Timeout: 2 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	response, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer response.Body.Close()
	if response.StatusCode != 200 {
		return "", errors.New("release check unavailable")
	}
	raw, err := io.ReadAll(io.LimitReader(response.Body, 2*1024*1024+1))
	if err != nil || len(raw) > 2*1024*1024 {
		return "", errors.New("invalid release list")
	}
	return latestCLITag(raw)
}
func installedSkillVersions(dir string) map[string]string {
	if dir == "" {
		dir = os.Getenv("FMG_SKILL_DIR")
	}
	if dir == "" {
		root := os.Getenv("CODEX_HOME")
		if root == "" {
			home, _ := os.UserHomeDir()
			root = filepath.Join(home, ".codex")
		}
		dir = filepath.Join(root, "skills")
	}
	versions := map[string]string{}
	for _, name := range []string{"fmg-api", "fmg-research"} {
		versions[name] = "unknown"
		if stat, err := os.Stat(filepath.Join(dir, name, "SKILL.md")); err != nil || !stat.Mode().IsRegular() {
			continue
		}
		var marker struct {
			Version string `json:"version"`
		}
		raw, err := os.ReadFile(filepath.Join(dir, name, ".fmg-release.json"))
		if err == nil && json.Unmarshal(raw, &marker) == nil {
			if _, ok := versionParts(marker.Version); ok {
				versions[name] = marker.Version
			}
		}
	}
	return versions
}
func localUpdateInfo(ctx context.Context, dir string, refresh bool) updateInfo {
	path, err := configPath()
	if err != nil {
		return updateInfo{Status: "check_unavailable"}
	}
	return checkUpdates(ctx, filepath.Join(filepath.Dir(path), "updates.json"), Version, installedSkillVersions(dir), refresh, time.Now(), publishedVersion)
}
func automaticUpdateNotice(ctx context.Context, stderr io.Writer) {
	if os.Getenv("FMG_NO_UPDATE_CHECK") == "1" {
		return
	}
	config, err := loadConfig()
	// No background Internet checks for unauthenticated or local-development gateways.
	if err != nil || !strings.HasPrefix(config.Server, "https://") {
		return
	}
	info := localUpdateInfo(ctx, "", false)
	if info.Status == "update_available" || info.Status == "skill_version_unknown" {
		_ = json.NewEncoder(stderr).Encode(map[string]any{"event": "fmg_update_notice", "update": info})
	}
}
func runUpdateCheck(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	if len(args) == 0 || args[0] != "check" {
		return writeError(stderr, errors.New("use fmg update check [--refresh] [--skill-dir DIRECTORY]"))
	}
	flags := flag.NewFlagSet("update check", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	refresh := flags.Bool("refresh", false, "bypass cached version check")
	dir := flags.String("skill-dir", "", "installed Skills directory")
	if flags.Parse(args[1:]) != nil || flags.NArg() != 0 {
		return writeError(stderr, errors.New("invalid update check arguments"))
	}
	if err := emit(stdout, localUpdateInfo(ctx, *dir, *refresh)); err != nil {
		return writeError(stderr, err)
	}
	return 0
}

package fmg

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"time"
)

func latestCLITag(raw []byte) (string, error) {
	var releases []struct {
		Tag   string `json:"tag_name"`
		Draft bool   `json:"draft"`
	}
	if json.Unmarshal(raw, &releases) != nil {
		return "", errors.New("invalid releases")
	}
	pattern := regexp.MustCompile(`^fmg-v([0-9]+)\.([0-9]+)\.([0-9]+)$`)
	best := [3]int{-1, -1, -1}
	tag := ""
	for _, release := range releases {
		m := pattern.FindStringSubmatch(release.Tag)
		if release.Draft || m == nil {
			continue
		}
		var version [3]int
		valid := true
		for i := 0; i < 3; i++ {
			n, err := strconv.Atoi(m[i+1])
			if err != nil {
				valid = false
			}
			version[i] = n
		}
		if !valid {
			continue
		}
		for i := 0; i < 3; i++ {
			if version[i] > best[i] {
				best = version
				tag = release.Tag
				break
			}
			if version[i] < best[i] {
				break
			}
		}
	}
	if tag == "" {
		return "", errors.New("no published CLI release")
	}
	return tag, nil
}

func runSkillInstaller(ctx context.Context, script []byte, expected, tag, binDir, skillDir string, stdout, stderr io.Writer) error {
	if fmt.Sprintf("%x", sha256.Sum256(script)) != expected {
		return errors.New("installer checksum mismatch")
	}
	temp, err := os.MkdirTemp("", "fmg-upgrade-")
	if err != nil {
		return err
	}
	defer os.RemoveAll(temp)
	path := filepath.Join(temp, "install.py")
	if err := os.WriteFile(path, script, 0600); err != nil {
		return err
	}
	args := []string{path, "--tag", tag, "--skills", "--bin-dir", binDir}
	if skillDir != "" {
		args = append(args, "--skill-dir", skillDir)
	}
	cmd := exec.CommandContext(ctx, "python3", args...)
	cmd.Stdout = stdout
	cmd.Stderr = stderr
	if err := cmd.Run(); err != nil {
		return errors.New("CLI/Skill upgrade failed; inspect installer output, then verify installed version")
	}
	return nil
}

func installArchive(path string, data []byte, expected string) error {
	if fmt.Sprintf("%x", sha256.Sum256(data)) != expected {
		return errors.New("release checksum mismatch; previous binary retained")
	}
	z, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return err
	}
	defer z.Close()
	r := tar.NewReader(z)
	var binary []byte
	for {
		h, e := r.Next()
		if e == io.EOF {
			break
		}
		if e != nil {
			return e
		}
		if h.Name != "fmg" || h.Typeflag != tar.TypeReg || h.Size > 32*1024*1024 || binary != nil {
			return errors.New("unexpected release archive entry")
		}
		binary, e = io.ReadAll(io.LimitReader(r, 32*1024*1024+1))
		if e != nil || len(binary) > 32*1024*1024 {
			return errors.New("invalid release binary")
		}
	}
	if len(binary) == 0 {
		return errors.New("release contains no binary")
	}
	f, err := os.CreateTemp(filepath.Dir(path), ".fmg-upgrade-")
	if err != nil {
		return err
	}
	name := f.Name()
	defer os.Remove(name)
	if _, err = f.Write(binary); err == nil {
		err = f.Chmod(0755)
	}
	if err == nil {
		err = f.Sync()
	}
	closeErr := f.Close()
	if err != nil {
		return err
	}
	if closeErr != nil {
		return closeErr
	}
	return os.Rename(name, path)
}

func runUpgrade(ctx context.Context, args []string, stdout, stderr io.Writer) int {
	flags := flag.NewFlagSet("upgrade", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	tag := flags.String("tag", "", "explicit fmg-v release tag")
	latest := flags.Bool("latest", false, "newest published fmg CLI release")
	skills := flags.Bool("skills", false, "update matching Skills (Python 3 required)")
	skillDir := flags.String("skill-dir", "", "Skill installation directory")
	if flags.Parse(args) != nil || flags.NArg() != 0 || (*latest && *tag != "") || (!*latest && !regexp.MustCompile(`^fmg-v[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$`).MatchString(*tag)) || (*skillDir != "" && !*skills) {
		return writeError(stderr, errors.New("upgrade requires --tag fmg-vX.Y.Z"))
	}
	if (runtime.GOOS != "darwin" && runtime.GOOS != "linux") || (runtime.GOARCH != "arm64" && runtime.GOARCH != "amd64") {
		return writeError(stderr, errors.New("unsupported platform"))
	}
	client := &http.Client{Timeout: 60 * time.Second, CheckRedirect: func(req *http.Request, via []*http.Request) error {
		if req.URL.Scheme != "https" || len(via) > 5 {
			return errors.New("unsafe download redirect")
		}
		return nil
	}}
	get := func(url string) ([]byte, error) {
		if !strings.HasPrefix(url, "https://") {
			return nil, errors.New("release URL must be HTTPS")
		}
		req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return nil, err
		}
		req.Header.Set("User-Agent", "fmg-cli")
		res, err := client.Do(req)
		if err != nil {
			return nil, errors.New("release download failed")
		}
		defer res.Body.Close()
		if res.StatusCode != 200 {
			return nil, errors.New("release asset unavailable")
		}
		b, err := io.ReadAll(io.LimitReader(res.Body, 32*1024*1024+1))
		if err != nil || len(b) > 32*1024*1024 {
			return nil, errors.New("invalid release download")
		}
		return b, nil
	}
	if *latest {
		raw, err := get("https://api.github.com/repos/Cedar-Zhang-OUTPUT/FindMeGamer/releases?per_page=100")
		if err != nil {
			return writeError(stderr, err)
		}
		selected, err := latestCLITag(raw)
		if err != nil {
			return writeError(stderr, err)
		}
		*tag = selected
	}
	raw, err := get("https://api.github.com/repos/Cedar-Zhang-OUTPUT/FindMeGamer/releases/tags/" + *tag)
	if err != nil {
		return writeError(stderr, err)
	}
	var release struct {
		Tag    string `json:"tag_name"`
		Assets []struct {
			Name string `json:"name"`
			URL  string `json:"browser_download_url"`
		} `json:"assets"`
	}
	if json.Unmarshal(raw, &release) != nil || release.Tag != *tag {
		return writeError(stderr, errors.New("invalid release metadata"))
	}
	name := "fmg_" + runtime.GOOS + "_" + runtime.GOARCH + ".tar.gz"
	urls := map[string]string{}
	for _, asset := range release.Assets {
		if strings.HasPrefix(asset.URL, "https://github.com/Cedar-Zhang-OUTPUT/FindMeGamer/releases/download/"+*tag+"/") {
			urls[asset.Name] = asset.URL
		}
	}
	sums, err := get(urls["SHA256SUMS"])
	if err != nil {
		return writeError(stderr, err)
	}
	if *skills {
		expected := ""
		for _, line := range strings.Split(string(sums), "\n") {
			p := strings.Fields(line)
			if len(p) == 2 && p[1] == "install.py" {
				expected = p[0]
			}
		}
		script, err := get(urls["install.py"])
		if err != nil {
			return writeError(stderr, err)
		}
		path, err := os.Executable()
		if err != nil {
			return writeError(stderr, err)
		}
		path, err = filepath.EvalSymlinks(path)
		if err != nil {
			return writeError(stderr, err)
		}
		if err := runSkillInstaller(ctx, script, expected, *tag, filepath.Dir(path), *skillDir, stdout, stderr); err != nil {
			return writeError(stderr, err)
		}
		return 0
	}
	expected := ""
	for _, line := range strings.Split(string(sums), "\n") {
		p := strings.Fields(line)
		if len(p) == 2 && p[1] == name {
			expected = p[0]
		}
	}
	data, err := get(urls[name])
	if err != nil {
		return writeError(stderr, err)
	}
	path, err := os.Executable()
	if err != nil {
		return writeError(stderr, err)
	}
	path, err = filepath.EvalSymlinks(path)
	if err != nil {
		return writeError(stderr, err)
	}
	if err = installArchive(path, data, expected); err != nil {
		return writeError(stderr, err)
	}
	emit(stdout, map[string]string{"installed_tag": *tag, "path": path, "skills": "unchanged; use installer --skills for a matching Skill update"})
	return 0
}

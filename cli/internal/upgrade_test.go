package fmg

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"fmt"
	"os"
	"path/filepath"
	"testing"
)

func archiveFor(t *testing.T, name string) []byte {
	t.Helper()
	var b bytes.Buffer
	z := gzip.NewWriter(&b)
	a := tar.NewWriter(z)
	data := []byte("new binary")
	a.WriteHeader(&tar.Header{Name: name, Mode: 0755, Size: int64(len(data)), Typeflag: tar.TypeReg})
	a.Write(data)
	a.Close()
	z.Close()
	return b.Bytes()
}

func TestLatestCLITagIgnoresDesktopDraftAndSuffix(t *testing.T) {
	tag, err := latestCLITag([]byte(`[{"tag_name":"v99.0.0"},{"tag_name":"fmg-v0.9.0"},{"tag_name":"fmg-v0.10.0","prerelease":true},{"tag_name":"fmg-v9.0.0","draft":true},{"tag_name":"fmg-v10.0.0-dev"}]`))
	if err != nil || tag != "fmg-v0.10.0" {
		t.Fatalf("%s %v", tag, err)
	}
}

func TestVerifiedInstallerReceivesPathsAndPreservesAuth(t *testing.T) {
	dir := t.TempDir()
	script := []byte("import sys,json\nprint(json.dumps(sys.argv[1:]))\n")
	sum := fmt.Sprintf("%x", sha256.Sum256(script))
	var out, errs bytes.Buffer
	if err := runSkillInstaller(context.Background(), script, "bad", "fmg-v0.2.0", dir, dir, &out, &errs); err == nil {
		t.Fatal("accepted bad checksum")
	}
	if out.Len() != 0 {
		t.Fatal("executed unverified script")
	}
	if err := runSkillInstaller(context.Background(), script, sum, "fmg-v0.2.0", dir, dir, &out, &errs); err != nil {
		t.Fatal(err)
	}
	if !bytes.Contains(out.Bytes(), []byte(`"--skills"`)) || !bytes.Contains(out.Bytes(), []byte(`"--skill-dir"`)) {
		t.Fatal(out.String())
	}
}
func TestVerifiedInstallPreservesOldOnBadHashOrArchive(t *testing.T) {
	path := filepath.Join(t.TempDir(), "fmg")
	os.WriteFile(path, []byte("old"), 0755)
	data := archiveFor(t, "fmg")
	if installArchive(path, data, "wrong") == nil {
		t.Fatal("accepted bad hash")
	}
	old, _ := os.ReadFile(path)
	if string(old) != "old" {
		t.Fatal("overwrote old")
	}
	bad := archiveFor(t, "../fmg")
	sum := fmt.Sprintf("%x", sha256.Sum256(bad))
	if installArchive(path, bad, sum) == nil {
		t.Fatal("accepted traversal")
	}
	sum = fmt.Sprintf("%x", sha256.Sum256(data))
	if err := installArchive(path, data, sum); err != nil {
		t.Fatal(err)
	}
	installed, _ := os.ReadFile(path)
	if string(installed) != "new binary" {
		t.Fatal("wrong binary")
	}
}

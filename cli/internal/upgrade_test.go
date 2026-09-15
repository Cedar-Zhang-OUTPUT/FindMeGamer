package fmg

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
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

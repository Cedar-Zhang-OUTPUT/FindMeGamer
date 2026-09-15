package main

import (
	"context"
	fmg "github.com/Cedar-Zhang-OUTPUT/FindMeGamer/cli/internal"
	"os"
	"os/signal"
	"syscall"
)

var version = "0.1.0-dev"

func main() {
	fmg.Version = version
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	os.Exit(fmg.RunContext(ctx, os.Args[1:], os.Stdin, os.Stdout, os.Stderr))
}

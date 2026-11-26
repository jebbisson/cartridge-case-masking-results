package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"cartridge-case-workbench/internal/reviewapp"
)

func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}
func run() error {
	addr := flag.String("addr", "127.0.0.1:8787", "HTTP listen address (loopback unless container mode is enabled)")
	db := flag.String("db", "review.sqlite", "SQLite database path")
	manifest := flag.String("manifest", "", "optional pilot manifest JSONL to seed")
	proposals := flag.String("proposals", "", "optional external proposal index JSONL")
	correctPinLabels := flag.Bool("correct-training-pin-labels", false, "correct pilot-v1 TRAIN pin source references before importing proposals")
	web := flag.String("web", "web/dist", "built UI directory (empty disables static files)")
	python := flag.String("python", "", "Python executable (defaults to python3)")
	worker := flag.String("worker", "python/multiscale_worker.py", "local Python worker script")
	flag.Parse()
	if err := checkAddr(*addr); err != nil {
		return err
	}
	if *db == "" {
		return errors.New("-db must not be empty")
	}
	if err := os.MkdirAll(filepath.Dir(*db), 0700); err != nil {
		return err
	}
	a, err := reviewapp.Open(*db, reviewapp.Options{Web: *web, Python: *python, Worker: *worker})
	if err != nil {
		return err
	}
	defer a.Close()
	if *manifest != "" {
		if err := a.Seed(*manifest); err != nil {
			return fmt.Errorf("seed: %w", err)
		}
	}
	if *correctPinLabels {
		n, err := a.CorrectTrainingPinLabels()
		if err != nil {
			return fmt.Errorf("correct training pin labels: %w", err)
		}
		log.Printf("training pin label correction: %d source revisions added", n)
	}
	if *proposals != "" {
		if err := a.ImportProposals(*proposals); err != nil {
			return fmt.Errorf("proposals: %w", err)
		}
	}
	listener, err := net.Listen("tcp4", *addr)
	if err != nil {
		return err
	}
	server := &http.Server{Handler: localOnly(a.Handler()), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 45 * time.Second, WriteTimeout: 3 * time.Minute, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 << 10}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	done := make(chan error, 1)
	log.Printf("review app listening on http://%s", listener.Addr())
	go func() { done <- server.Serve(listener) }()
	select {
	case err := <-done:
		if !errors.Is(err, http.ErrServerClosed) {
			return err
		}
		return nil
	case <-ctx.Done():
		deadline, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := server.Shutdown(deadline); err != nil {
			_ = server.Close()
			return err
		}
		return nil
	}
}
func checkAddr(addr string) error {
	host, port, err := net.SplitHostPort(addr)
	// Docker forwards host loopback traffic to the container's network interface.
	container := os.Getenv("REVIEWAPP_CONTAINER_BIND") == "1"
	if err != nil || (host != "127.0.0.1" && !(container && host == "0.0.0.0")) {
		return errors.New("-addr must be 127.0.0.1:PORT")
	}
	if _, err := strconv.ParseUint(port, 10, 16); err != nil {
		return errors.New("invalid -addr port")
	}
	return nil
}
func localOnly(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		host := r.Host
		if h, _, err := net.SplitHostPort(host); err == nil {
			host = h
		}
		if !strings.EqualFold(host, "localhost") && host != "127.0.0.1" {
			http.Error(w, "loopback host required", 403)
			return
		}
		if r.Method == http.MethodPost {
			if r.Header.Get("Sec-Fetch-Site") == "cross-site" {
				http.Error(w, "cross-site write rejected", 403)
				return
			}
			if origin := r.Header.Get("Origin"); origin != "" {
				u, err := url.Parse(origin)
				if err != nil || u.User != nil || (u.Scheme != "http" && u.Scheme != "https") || !strings.EqualFold(u.Host, r.Host) {
					http.Error(w, "cross-origin write rejected", 403)
					return
				}
			}
		}
		next.ServeHTTP(w, r)
	})
}

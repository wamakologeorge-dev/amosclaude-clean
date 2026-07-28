// Amosclaudd is a small cross-platform supervisor for the local FastAPI node.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"runtime"
	"strconv"
	"syscall"
	"time"
)

type config struct {
	root       string
	python     string
	host       string
	port       int
	healthWait time.Duration
}

func parseConfig() config {
	var cfg config
	flag.StringVar(&cfg.root, "root", ".", "Amosclaud repository root")
	flag.StringVar(&cfg.python, "python", "python", "Python executable")
	flag.StringVar(&cfg.host, "host", "127.0.0.1", "FastAPI bind host")
	flag.IntVar(&cfg.port, "port", 8765, "FastAPI bind port")
	flag.DurationVar(&cfg.healthWait, "health-timeout", 30*time.Second, "startup health timeout")
	flag.Parse()
	return cfg
}

func repositoryRoot(value string) (string, error) {
	root, err := filepath.Abs(value)
	if err != nil {
		return "", fmt.Errorf("resolve repository root: %w", err)
	}
	info, err := os.Stat(filepath.Join(root, "scripts", "run_local_cloud.py"))
	if err != nil {
		return "", fmt.Errorf("local cloud launcher not found: %w", err)
	}
	if info.IsDir() {
		return "", errors.New("local cloud launcher is not a file")
	}
	return root, nil
}

func localHealthURL(host string, port int) (string, error) {
	if host != "127.0.0.1" && host != "localhost" && host != "::1" {
		return "", errors.New("amosclaudd health supervision is loopback-only")
	}
	if port < 1 || port > 65535 {
		return "", errors.New("port is outside the valid range")
	}
	if host == "::1" {
		return "http://[::1]:" + strconv.Itoa(port) + "/live", nil
	}
	return "http://" + host + ":" + strconv.Itoa(port) + "/live", nil
}

func waitForHealth(ctx context.Context, url string, timeout time.Duration) error {
	client := &http.Client{Timeout: 2 * time.Second}
	deadline := time.NewTimer(timeout)
	defer deadline.Stop()
	ticker := time.NewTicker(350 * time.Millisecond)
	defer ticker.Stop()

	for {
		request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
		if err != nil {
			return err
		}
		response, err := client.Do(request)
		if err == nil {
			response.Body.Close()
			if response.StatusCode >= 200 && response.StatusCode < 300 {
				return nil
			}
		}
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-deadline.C:
			return errors.New("FastAPI node did not become healthy before timeout")
		case <-ticker.C:
		}
	}
}

func terminateProcess(command *exec.Cmd) {
	if command.Process == nil {
		return
	}
	if runtime.GOOS == "windows" {
		_ = command.Process.Kill()
		return
	}
	_ = command.Process.Signal(syscall.SIGTERM)
}

func run(cfg config) error {
	root, err := repositoryRoot(cfg.root)
	if err != nil {
		return err
	}
	healthURL, err := localHealthURL(cfg.host, cfg.port)
	if err != nil {
		return err
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	command := exec.CommandContext(ctx, cfg.python, "scripts/run_local_cloud.py")
	command.Dir = root
	command.Stdout = os.Stdout
	command.Stderr = os.Stderr
	command.Stdin = os.Stdin
	command.Env = append(
		os.Environ(),
		"AMOSCLAUD_LOCAL_HOST="+cfg.host,
		"AMOSCLAUD_LOCAL_PORT="+strconv.Itoa(cfg.port),
	)
	if err := command.Start(); err != nil {
		return fmt.Errorf("start FastAPI node: %w", err)
	}

	waitResult := make(chan error, 1)
	go func() {
		waitResult <- command.Wait()
	}()

	if err := waitForHealth(ctx, healthURL, cfg.healthWait); err != nil {
		terminateProcess(command)
		<-waitResult
		return err
	}
	log.Printf("Amosclaud local node ready at http://%s:%d", cfg.host, cfg.port)

	select {
	case <-ctx.Done():
		log.Printf("shutdown requested")
		terminateProcess(command)
		err := <-waitResult
		if err != nil && !errors.Is(err, context.Canceled) {
			return fmt.Errorf("FastAPI node stopped during shutdown: %w", err)
		}
		return nil
	case err := <-waitResult:
		if err != nil {
			return fmt.Errorf("FastAPI node exited: %w", err)
		}
		return errors.New("FastAPI node exited unexpectedly")
	}
}

func main() {
	if err := run(parseConfig()); err != nil {
		log.Fatal(err)
	}
}

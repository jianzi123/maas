// maas-probe checks loopback health endpoints without a shell, proxy or body logging.
package main

import (
	"fmt"
	"net"
	"net/http"
	"net/url"
	"os"
	"time"
)

func check(target string) error {
	u, err := url.Parse(target)
	if err != nil || u.Scheme != "http" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Errorf("invalid probe URL")
	}
	ip := net.ParseIP(u.Hostname())
	if ip == nil || !ip.IsLoopback() {
		return fmt.Errorf("probe must target a loopback IP")
	}
	c := &http.Client{
		Timeout:       2 * time.Second,
		Transport:     &http.Transport{Proxy: nil},
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	}
	resp, err := c.Get(u.String())
	if err != nil {
		return fmt.Errorf("health endpoint unavailable")
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("health endpoint rejected")
	}
	return nil
}

func main() {
	if len(os.Args) != 2 || check(os.Args[1]) != nil {
		fmt.Fprintln(os.Stderr, "probe failed")
		os.Exit(1)
	}
}

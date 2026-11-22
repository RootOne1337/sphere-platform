// A bounded independent WG/AWG data-path probe. The tunnel is an in-memory
// gVisor stack: no OS TUN, adapter, driver, routes or firewall are created.
// Supply private input only through stdin; never put keys in command arguments.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/netip"
	"os"
	"strings"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/device"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/netstack"
)

type input struct {
	Config    string
	Addresses []string
	Dns       []string
}

func decode(r io.Reader) (input, []netip.Addr, []netip.Addr, error) {
	var in input
	raw, err := io.ReadAll(io.LimitReader(r, 16385))
	if err != nil || len(raw) > 16384 {
		return in, nil, nil, fmt.Errorf("input_bounds")
	}
	d := json.NewDecoder(bytes.NewReader(raw))
	d.DisallowUnknownFields()
	if d.Decode(&in) != nil || d.Decode(new(any)) != io.EOF || len(in.Config) < 1 || len(in.Config) > 8192 ||
		len(in.Addresses) < 1 || len(in.Addresses) > 2 || len(in.Dns) < 1 || len(in.Dns) > 2 {
		return input{}, nil, nil, fmt.Errorf("input_invalid")
	}
	parse := func(values []string) ([]netip.Addr, error) {
		var result []netip.Addr
		for _, s := range values {
			a, err := netip.ParseAddr(s)
			if err != nil || a.Zone() != "" || a.IsUnspecified() || a.IsMulticast() {
				return nil, fmt.Errorf("address_invalid")
			}
			result = append(result, a)
		}
		return result, nil
	}
	a, err := parse(in.Addresses)
	if err != nil {
		return input{}, nil, nil, err
	}
	dns, err := parse(in.Dns)
	return in, a, dns, err
}

func run(r io.Reader, out io.Writer) error {
	in, addresses, dns, err := decode(r)
	if err != nil {
		return err
	}
	tun, stack, err := netstack.CreateNetTUN(addresses, dns, 1280)
	if err != nil {
		return fmt.Errorf("memory_stack_failed")
	}
	// Upstream diagnostics may contain secrets: no native logger is forwarded.
	logger := &device.Logger{Verbosef: func(string, ...any) {}, Errorf: func(string, ...any) {}}
	engine := device.NewDevice(tun, conn.NewDefaultBind(), logger)
	defer engine.Close()
	if engine.IpcSet(in.Config) != nil || engine.Up() != nil {
		return fmt.Errorf("engine_failed")
	}
	in.Config = ""
	ctx, cancel := context.WithTimeout(context.Background(), 28*time.Second)
	defer cancel()
	transport := &http.Transport{DialContext: func(ctx context.Context, network, address string) (net.Conn, error) {
		return stack.DialContext(ctx, network, address)
	}, DisableKeepAlives: true, Proxy: nil}
	defer transport.CloseIdleConnections()
	client := &http.Client{Transport: transport, Timeout: 8 * time.Second,
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	enc := json.NewEncoder(out)
	for _, url := range []string{"http://1.1.1.1/cdn-cgi/trace", "https://1.1.1.1/cdn-cgi/trace", "https://www.cloudflare.com/cdn-cgi/trace"} {
		started := time.Now()
		result := map[string]any{"url": url, "confirmed": false}
		req, _ := http.NewRequestWithContext(ctx, "GET", url, nil)
		resp, err := client.Do(req)
		if err != nil {
			// Error text can contain endpoints. Emit only a stable class.
			result["code"] = "request_failed"
		} else {
			body, readErr := io.ReadAll(io.LimitReader(resp.Body, 8193))
			resp.Body.Close()
			result["status"] = resp.StatusCode
			if readErr == nil && len(body) <= 8192 && resp.StatusCode == 200 {
				for _, line := range strings.Split(string(body), "\n") {
					if strings.HasPrefix(line, "ip=") {
						if addr, parseErr := netip.ParseAddr(strings.TrimPrefix(line, "ip=")); parseErr == nil {
							result["egressIp"] = addr.String()
							result["confirmed"] = true
						}
					}
				}
			}
		}
		result["elapsedMs"] = time.Since(started).Milliseconds()
		if err := enc.Encode(result); err != nil {
			return fmt.Errorf("output_failed")
		}
	}
	// Never print IpcGet raw: it includes the private key.
	status, err := engine.IpcGet()
	if err != nil {
		return fmt.Errorf("status_failed")
	}
	counters := map[string]any{"osNetworkChanged": false}
	for _, line := range strings.Split(status, "\n") {
		key, value, found := strings.Cut(line, "=")
		if found && (key == "last_handshake_time_sec" || key == "rx_bytes" || key == "tx_bytes") {
			var n uint64
			if _, err := fmt.Sscan(value, &n); err == nil {
				counters[key] = n
			}
		}
	}
	return enc.Encode(counters)
}

func main() {
	if err := run(os.Stdin, os.Stdout); err != nil {
		// These are exclusively our stable codes, never upstream parser errors.
		json.NewEncoder(os.Stderr).Encode(map[string]string{"code": err.Error()})
		os.Exit(1)
	}
}

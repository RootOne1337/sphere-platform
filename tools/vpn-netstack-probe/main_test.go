package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestInvalidInputNeverStartsNetworkingOrEchoesPrivateInput(t *testing.T) {
	for _, raw := range []string{"private-sentinel", strings.Repeat("x", 16385),
		`{"Config":"private-sentinel","Addresses":["invalid"],"Dns":["1.1.1.1"]}`,
		`{"Config":"private-sentinel","Addresses":["10.0.0.1"],"Dns":[],"Extra":true}`,
		`{"Config":"private-sentinel","Addresses":[],"Dns":["1.1.1.1"]}`} {
		var output strings.Builder
		err := run(strings.NewReader(raw), &output)
		if err == nil || strings.Contains(err.Error(), "private-sentinel") || output.Len() != 0 {
			t.Fatal("input validation boundary failed")
		}
	}
}

func TestDecodeIsBoundedAndDoesNotRequireHostAdapter(t *testing.T) {
	raw, _ := json.Marshal(input{Config: "private-sentinel", Addresses: []string{"10.0.0.2", "fd42::2"}, Dns: []string{"1.1.1.1"}})
	in, a, dns, err := decode(strings.NewReader(string(raw)))
	if err != nil || len(a) != 2 || len(dns) != 1 || in.Config != "private-sentinel" {
		t.Fatal("valid private input rejected")
	}
	if _, _, _, err := decode(strings.NewReader(string(raw) + `{}`)); err == nil {
		t.Fatal("trailing document accepted")
	}
}

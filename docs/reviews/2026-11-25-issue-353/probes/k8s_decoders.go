// Measures how Kubernetes' decoders read a lone surrogate (#353).
package main

import (
	"encoding/json"
	"fmt"

	kjson "sigs.k8s.io/json"
	"sigs.k8s.io/yaml"
)

func main() {
	var a, b map[string]string
	if err := json.Unmarshal([]byte(`{"a":"a\ud800"}`), &a); err != nil {
		fmt.Println("encoding/json error:", err)
	}
	fmt.Printf("encoding/json: %q\n", a["a"])
	if err := kjson.UnmarshalCaseSensitivePreserveInts([]byte(`{"a":"a\ud800"}`), &b); err != nil {
		fmt.Println("sigs.k8s.io/json error:", err)
	}
	fmt.Printf("sigs.k8s.io/json: %q\n", b["a"])
	var c map[string]string
	// The bytes PyYAML 6.0.2 wrote for {"a": "a\ud800"} (measured).
	err := yaml.Unmarshal([]byte("a: \"a\\uD800\"\n"), &c)
	fmt.Printf("sigs.k8s.io/yaml: %q err=%v\n", c["a"], err)
}

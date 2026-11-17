// yamlread reads one YAML document from stdin the way Kubernetes tooling reads a manifest, and prints what each reader
// made of it as JSON (#355):
//
//	yaml11: sigs.k8s.io/yaml.YAMLToJSON, the YAML 1.1 reader (go-yaml v2) that kubectl, Argo CD and the Kyverno CLI use
//	yaml12: go-yaml v3 decoding into interface{}, the YAML 1.2 reader of kustomize's kyaml
//
// A value that is not a string, or a mapping key that is not a string, is written as "<type value>", so a caller can
// compare the result with the strings it meant to write. A reader that fails gives its error instead.
package main

import (
	"encoding/json"
	"fmt"
	"io"
	"math"
	"os"
	"time"

	yaml12 "go.yaml.in/yaml/v3"
	"sigs.k8s.io/yaml"
)

type result struct {
	YAML11      json.RawMessage `json:"yaml11"`
	YAML11Error string          `json:"yaml11_error,omitempty"`
	YAML12      interface{}     `json:"yaml12"`
	YAML12Error string          `json:"yaml12_error,omitempty"`
}

// mark keeps strings, mappings and sequences as they are and spells every other scalar with its Go type.
func mark(v interface{}) interface{} {
	switch t := v.(type) {
	case string:
		return t
	case map[string]interface{}:
		out := make(map[string]interface{}, len(t))
		for k, x := range t {
			out[k] = mark(x)
		}
		return out
	case map[interface{}]interface{}:
		out := make(map[string]interface{}, len(t))
		for k, x := range t {
			key, ok := k.(string)
			if !ok {
				key = fmt.Sprintf("<%T %v>", k, k)
			}
			out[key] = mark(x)
		}
		return out
	case []interface{}:
		out := make([]interface{}, len(t))
		for i, x := range t {
			out[i] = mark(x)
		}
		return out
	case float64:
		if math.IsInf(t, 0) || math.IsNaN(t) {
			return fmt.Sprintf("<float64 %v>", t)
		}
	case time.Time:
		return fmt.Sprintf("<time.Time %s>", t.Format(time.RFC3339Nano))
	}
	return fmt.Sprintf("<%T %v>", v, v)
}

// markJSON re-marks the JSON that YAMLToJSON gives: there a bool or a number is already a JSON bool or number.
func markJSON(v interface{}) interface{} {
	switch t := v.(type) {
	case map[string]interface{}:
		for k, x := range t {
			t[k] = markJSON(x)
		}
		return t
	case []interface{}:
		for i, x := range t {
			t[i] = markJSON(x)
		}
		return t
	case string:
		return t
	}
	return fmt.Sprintf("<%T %v>", v, v)
}

func main() {
	in, err := io.ReadAll(os.Stdin)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
	var r result
	if j, err := yaml.YAMLToJSON(in); err != nil {
		r.YAML11Error = err.Error()
	} else {
		var v interface{}
		if err := json.Unmarshal(j, &v); err != nil {
			r.YAML11Error = err.Error()
		} else if r.YAML11, err = json.Marshal(markJSON(v)); err != nil {
			r.YAML11Error = err.Error()
		}
	}
	var v interface{}
	if err := yaml12.Unmarshal(in, &v); err != nil {
		r.YAML12Error = err.Error()
	} else {
		r.YAML12 = mark(v)
	}
	if err := json.NewEncoder(os.Stdout).Encode(r); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(2)
	}
}

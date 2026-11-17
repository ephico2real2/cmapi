// RE2 (Go regexp, the dialect of CEL matches() in Kyverno) on tri_corpus.py's regexes; prints each verdict that differs.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
)

func main() {
	raw, _ := os.ReadFile(os.Args[1])
	var d struct {
		Regexes map[string]string `json:"regexes"`
		Corpus  []string          `json:"corpus"`
		Python  map[string][]bool `json:"python"`
	}
	if err := json.Unmarshal(raw, &d); err != nil {
		panic(err)
	}
	n, bad := 0, 0
	for name, rx := range d.Regexes {
		re, err := regexp.Compile(rx)
		if err != nil {
			fmt.Println("RE2 does not compile", name, err)
			bad++
			continue
		}
		for i, s := range d.Corpus {
			n++
			if re.MatchString(s) != d.Python[name][i] {
				bad++
				fmt.Printf("RE2 differs %s %q %v\n", name, s, re.MatchString(s))
			}
		}
	}
	fmt.Printf("re2: %d verdicts, %d differ from python\n", n, bad)
}

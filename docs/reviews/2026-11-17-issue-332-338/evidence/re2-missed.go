package main

import (
	"fmt"
	"regexp"
)

func main() {
	for _, p := range []string{`^a{,3}$`, `^a{1001}$`, `^(?:a{100}){11}$`, `^a]$`, `^a}$`, `^a{$`, `^\-$`, `^[a&&b]$`, `^\x41$`, `^[a-z]*+$`, `^(?>a)$`, `^a\Z`} {
		_, err := regexp.Compile("^(?:" + p + ")$")
		fmt.Printf("RE2 %-22s %v\n", p, err)
	}
}

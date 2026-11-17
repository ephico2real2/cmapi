package main

import (
	"fmt"
	"regexp"
)

func main() {
	for _, p := range []string{`^[a-z]+\Z`, `(?i)^[a-z]+$`, `^(?P<t>[a-z]+)$`, `^(?=x)[a-z]+$`, `^([a-z])\1$`} {
		_, err := regexp.Compile(p)
		fmt.Printf("RE2 %-20s %v\n", p, err)
	}
}

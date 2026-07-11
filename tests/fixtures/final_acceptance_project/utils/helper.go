package utils

import "fmt"

type GoHelper struct{}

func (h *GoHelper) FormatString(s string) string {
    return fmt.Sprintf("Go: %s", s)
}

func DoGoWork() {
    helper := &GoHelper{}
    fmt.Println(helper.FormatString("hello"))
}

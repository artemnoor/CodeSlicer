package processor

import (
	"fmt"
	"github.com/example/db"
)

type GoCalculator struct {
	ID string
}

func (c *GoCalculator) Compute(val int) int {
	res := val * 2
	db.SaveResult(res)
	return res
}

func ExecuteProcess() {
	calc := &GoCalculator{ID: "calc-1"}
	calc.Compute(42)
}

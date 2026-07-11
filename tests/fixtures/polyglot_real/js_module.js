import { helperFunc } from "./utils.js";

class Calculator {
    add(a, b) {
        return a + b;
    }
    
    multiply(a, b) {
        return a * b;
    }
}

function processCalculation() {
    const calc = new Calculator();
    const result = calc.add(5, 10);
    helperFunc(result);
}

import { Logger } from "./logger.ts";

export class OrderProcessor {
    private logger: Logger;
    
    constructor() {
        this.logger = new Logger();
    }
    
    public processOrder(orderId: string): void {
        this.logger.info("Processing order: " + orderId);
        this.saveToDatabase(orderId);
    }
    
    private saveToDatabase(orderId: string): void {
        // save order logic
    }
}

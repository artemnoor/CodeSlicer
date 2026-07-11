import { helper } from "external_lib";

class OrderService {
    createOrder(order: any) {
        helper();
        this.saveOrder(order);
    }
    
    saveOrder(order: any) {
        // save
    }
}

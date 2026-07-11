package com.example;

import com.other.Helper;

class OrderService {
    public void createOrder() {
        Helper.run();
        this.save();
    }
    public void save() {}
}

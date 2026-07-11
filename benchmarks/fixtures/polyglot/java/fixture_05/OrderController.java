package com.example.orders5;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository5 { public void save() {} }
class OrderService5 { private OrderRepository5 repository; public void create() { repository.save(); } }
@RestController class OrderController5 { private OrderService5 service; @GetMapping("/orders/5") public void get() { service.create(); } }

package com.example.orders4;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository4 { public void save() {} }
class OrderService4 { private OrderRepository4 repository; public void create() { repository.save(); } }
@RestController class OrderController4 { private OrderService4 service; @GetMapping("/orders/4") public void get() { service.create(); } }

package com.example.orders1;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository1 { public void save() {} }
class OrderService1 { private OrderRepository1 repository; public void create() { repository.save(); } }
@RestController class OrderController1 { private OrderService1 service; @GetMapping("/orders/1") public void get() { service.create(); } }

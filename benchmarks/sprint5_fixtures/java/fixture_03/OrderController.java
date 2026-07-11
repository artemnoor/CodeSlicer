package com.example.orders3;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository3 { public void save() {} }
class OrderService3 { private OrderRepository3 repository; public void create() { repository.save(); } }
@RestController class OrderController3 { private OrderService3 service; @GetMapping("/orders/3") public void get() { service.create(); } }

package com.example.orders8;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository8 { public void save() {} }
class OrderService8 { private OrderRepository8 repository; public void create() { repository.save(); } }
@RestController class OrderController8 { private OrderService8 service; @GetMapping("/orders/8") public void get() { service.create(); } }

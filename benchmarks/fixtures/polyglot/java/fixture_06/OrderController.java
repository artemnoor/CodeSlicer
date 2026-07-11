package com.example.orders6;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository6 { public void save() {} }
class OrderService6 { private OrderRepository6 repository; public void create() { repository.save(); } }
@RestController class OrderController6 { private OrderService6 service; @GetMapping("/orders/6") public void get() { service.create(); } }

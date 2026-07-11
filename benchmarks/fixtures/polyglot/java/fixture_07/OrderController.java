package com.example.orders7;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository7 { public void save() {} }
class OrderService7 { private OrderRepository7 repository; public void create() { repository.save(); } }
@RestController class OrderController7 { private OrderService7 service; @GetMapping("/orders/7") public void get() { service.create(); } }

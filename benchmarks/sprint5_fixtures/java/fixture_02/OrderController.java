package com.example.orders2;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

class OrderRepository2 { public void save() {} }
class OrderService2 { private OrderRepository2 repository; public void create() { repository.save(); } }
@RestController class OrderController2 { private OrderService2 service; @GetMapping("/orders/2") public void get() { service.create(); } }

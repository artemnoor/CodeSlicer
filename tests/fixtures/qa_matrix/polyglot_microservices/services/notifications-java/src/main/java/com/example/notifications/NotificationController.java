package com.example.notifications;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/notifications")
public class NotificationController {
    private final NotificationService notificationService;

    public NotificationController(NotificationService notificationService) {
        this.notificationService = notificationService;
    }

    @PostMapping("/send")
    public NotificationResponse sendNotification(@RequestBody NotificationRequest request) {
        return notificationService.send(request);
    }
}

record NotificationRequest(String recipient, String message) {
}

record NotificationResponse(String status, String providerId) {
}

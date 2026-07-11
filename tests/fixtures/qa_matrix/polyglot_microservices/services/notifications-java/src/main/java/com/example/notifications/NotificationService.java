package com.example.notifications;

public class NotificationService {
    private final NotificationClient notificationClient;

    public NotificationService(NotificationClient notificationClient) {
        this.notificationClient = notificationClient;
    }

    public NotificationResponse send(NotificationRequest request) {
        return notificationClient.post(request);
    }

    public NotificationResponse save(NotificationRequest request) {
        // Trap: method name resembles repository save methods but is not persistence.
        return new NotificationResponse("ignored-save-trap", "none");
    }
}

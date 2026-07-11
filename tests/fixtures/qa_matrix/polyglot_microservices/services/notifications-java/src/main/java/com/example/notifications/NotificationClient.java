package com.example.notifications;

public class NotificationClient {
    public NotificationResponse post(NotificationRequest request) {
        String providerId = "provider-" + request.recipient();
        return new NotificationResponse("sent", providerId);
    }
}

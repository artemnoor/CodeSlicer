package com.example.processor;

import com.example.db.DatabaseConnection;

public class JavaProcessor {
    private DatabaseConnection conn;
    
    public void executeTask(String taskId) {
        System.out.println("Executing: " + taskId);
        conn.save(taskId);
    }
}

package com.mathgrader.service;

import com.mathgrader.model.GradeRequest;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

@Service
public class GradeJobSessionService {
    private final Map<String, PendingGradeSession> sessions = new ConcurrentHashMap<>();

    public void register(String jobId, String traceId, GradeRequest request, String username) {
        if (jobId == null || jobId.isBlank()) {
            return;
        }
        sessions.put(jobId, new PendingGradeSession(jobId, traceId, request, username));
    }

    public PendingGradeSession get(String jobId) {
        return sessions.get(jobId);
    }

    public void remove(String jobId) {
        if (jobId == null || jobId.isBlank()) {
            return;
        }
        sessions.remove(jobId);
    }

    public static class PendingGradeSession {
        private final String jobId;
        private final String traceId;
        private final GradeRequest request;
        private final String username;
        private volatile boolean saved;

        public PendingGradeSession(String jobId, String traceId, GradeRequest request, String username) {
            this.jobId = jobId;
            this.traceId = traceId;
            this.request = request;
            this.username = username;
            this.saved = false;
        }

        public String getJobId() {
            return jobId;
        }

        public String getTraceId() {
            return traceId;
        }

        public GradeRequest getRequest() {
            return request;
        }

        public String getUsername() {
            return username;
        }

        public boolean isSaved() {
            return saved;
        }

        public void markSaved() {
            this.saved = true;
        }
    }
}

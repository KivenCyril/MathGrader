package com.mathgrader.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.Map;

@Service
public class PythonAgentBridgeService {

    private final WebClient webClient;
    
    @Value("${python.agent.url:http://localhost:5000}")
    private String pythonAgentUrl;

    public PythonAgentBridgeService(WebClient.Builder webClientBuilder) {
        this.webClient = webClientBuilder.build();
    }

    public GradeResponse callPythonAgent(GradeRequest request) {
        try {
            // Forward request to Python Agent
            // Request body matches Python's expectation
            // Python expects: { questionText, standardAnswer, studentAnswer, maxScore, mode }
            
            // We can reuse GradeRequest or map it. Since field names match or we can adapt.
            // Let's assume GradeRequest fields match what Python needs or we map them here.
            // Python: questionText, standardAnswer, studentAnswer, maxScore
            // Java GradeRequest: same fields (lombok @Data)
            
            // Add 'mode' if needed, for now default or from request if we add it
            
            return webClient.post()
                    .uri(pythonAgentUrl + "/grade")
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(GradeResponse.class)
                    .timeout(Duration.ofSeconds(60)) // Give LLM enough time
                    .block(); // Blocking for simplicity in this architecture
                    
        } catch (Exception e) {
            GradeResponse error = new GradeResponse();
            error.setCorrect(false);
            error.setScore(0);
            error.setReason("Java Bridge Error: Failed to call Python Agent. " + e.getMessage());
            return error;
        }
    }
}

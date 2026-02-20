package com.mathgrader.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

import java.time.Duration;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.BodyInserters;

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
            return webClient.post()
                    .uri(pythonAgentUrl + "/grade")
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(GradeResponse.class)
                    .timeout(Duration.ofSeconds(120)) 
                    .block(); 
                    
        } catch (Exception e) {
            GradeResponse error = new GradeResponse();
            error.setCorrect(false);
            error.setScore(0);
            error.setReason("Java Bridge Error: Failed to call Python Agent. " + e.getMessage());
            return error;
        }
    }

    public Map<String, String> performOcr(MultipartFile file) {
        try {
            MultipartBodyBuilder builder = new MultipartBodyBuilder();
            builder.part("file", file.getResource());

            return webClient.post()
                    .uri(pythonAgentUrl + "/ocr")
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(builder.build()))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
        } catch (Exception e) {
            return Map.of("error", "OCR Error: " + e.getMessage());
        }
    }

    public Map<String, String> solveQuestion(Map<String, Object> payload) {
        try {
            return webClient.post()
                    .uri(pythonAgentUrl + "/solve")
                    .bodyValue(payload)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(120))
                    .block();
        } catch (Exception e) {
            return Map.of("error", "Solver Error: " + e.getMessage());
        }
    }

    public List<String> getAvailableModels() {
        try {
            return webClient.get()
                    .uri(pythonAgentUrl + "/models")
                    .retrieve()
                    .bodyToMono(List.class)
                    .timeout(Duration.ofSeconds(5))
                    .block();
        } catch (Exception e) {
            return List.of("default");
        }
    }
}

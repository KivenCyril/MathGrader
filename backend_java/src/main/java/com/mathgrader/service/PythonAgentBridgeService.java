package com.mathgrader.service;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.http.client.MultipartBodyBuilder;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.reactive.function.BodyInserters;
import org.springframework.web.reactive.function.client.WebClient;

import java.time.Duration;
import java.util.List;
import java.util.Map;

@Service
public class PythonAgentBridgeService {
    private static final Logger log = LoggerFactory.getLogger(PythonAgentBridgeService.class);

    private final WebClient webClient;
    
    @Value("${python.agent.url:http://localhost:5000}")
    private String pythonAgentUrl;

    public PythonAgentBridgeService(WebClient.Builder webClientBuilder) {
        this.webClient = webClientBuilder.build();
    }

    private long elapsedMs(long startedAtNanos) {
        return (System.nanoTime() - startedAtNanos) / 1_000_000;
    }

    public GradeResponse callPythonAgent(GradeRequest request, String traceId) {
        long startedAt = System.nanoTime();
        try {
            GradeResponse response = webClient.post()
                    .uri(pythonAgentUrl + "/grade")
                    .header("X-Trace-Id", traceId)
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(GradeResponse.class)
                    .timeout(Duration.ofSeconds(120)) 
                    .block();
            log.info("[Bridge][{}] /grade completed in {} ms", traceId, elapsedMs(startedAt));
            return response;
                    
        } catch (Exception e) {
            log.warn("[Bridge][{}] /grade failed after {} ms: {}", traceId, elapsedMs(startedAt), e.getMessage());
            GradeResponse error = new GradeResponse();
            error.setCorrect(false);
            error.setScore(0);
            error.setReason("Java Bridge Error: Failed to call Python Agent. " + e.getMessage());
            return error;
        }
    }

    public Map<String, Object> submitGradeJob(GradeRequest request, String traceId) {
        long startedAt = System.nanoTime();
        try {
            Map<String, Object> response = webClient.post()
                    .uri(pythonAgentUrl + "/grade/submit")
                    .header("X-Trace-Id", traceId)
                    .bodyValue(request)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            log.info("[Bridge][{}] /grade/submit completed in {} ms", traceId, elapsedMs(startedAt));
            return response;
        } catch (Exception e) {
            log.warn("[Bridge][{}] /grade/submit failed after {} ms: {}", traceId, elapsedMs(startedAt), e.getMessage());
            return Map.of("status", "failed", "error", "Failed to submit grade job. " + e.getMessage());
        }
    }

    public Map<String, Object> fetchGradeJobProgress(String jobId, String traceId) {
        long startedAt = System.nanoTime();
        try {
            Map<String, Object> response = webClient.get()
                    .uri(pythonAgentUrl + "/grade/jobs/" + jobId)
                    .header("X-Trace-Id", traceId)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            log.info("[Bridge][{}] /grade/jobs/{} completed in {} ms", traceId, jobId, elapsedMs(startedAt));
            return response;
        } catch (Exception e) {
            log.warn("[Bridge][{}] /grade/jobs/{} failed after {} ms: {}", traceId, jobId, elapsedMs(startedAt), e.getMessage());
            return Map.of("jobId", jobId, "status", "failed", "error", "Failed to fetch grade progress. " + e.getMessage());
        }
    }

    public Map<String, String> performOcr(MultipartFile file, String traceId) {
        long startedAt = System.nanoTime();
        try {
            MultipartBodyBuilder builder = new MultipartBodyBuilder();
            builder.part("file", file.getResource());

            Map<String, String> response = webClient.post()
                    .uri(pythonAgentUrl + "/ocr")
                    .header("X-Trace-Id", traceId)
                    .contentType(MediaType.MULTIPART_FORM_DATA)
                    .body(BodyInserters.fromMultipartData(builder.build()))
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(30))
                    .block();
            log.info("[Bridge][{}] /ocr completed in {} ms", traceId, elapsedMs(startedAt));
            return response;
        } catch (Exception e) {
            log.warn("[Bridge][{}] /ocr failed after {} ms: {}", traceId, elapsedMs(startedAt), e.getMessage());
            return Map.of("error", "OCR Error: " + e.getMessage());
        }
    }

    public Map<String, Object> solveQuestion(Map<String, Object> payload, String traceId) {
        long startedAt = System.nanoTime();
        try {
            Map<String, Object> response = webClient.post()
                    .uri(pythonAgentUrl + "/solve")
                    .header("X-Trace-Id", traceId)
                    .bodyValue(payload)
                    .retrieve()
                    .bodyToMono(Map.class)
                    .timeout(Duration.ofSeconds(120))
                    .block();
            log.info("[Bridge][{}] /solve completed in {} ms", traceId, elapsedMs(startedAt));
            return response;
        } catch (Exception e) {
            log.warn("[Bridge][{}] /solve failed after {} ms: {}", traceId, elapsedMs(startedAt), e.getMessage());
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

    public List<Map<String, Object>> getGradingMethods() {
        try {
            return webClient.get()
                    .uri(pythonAgentUrl + "/grading-methods")
                    .retrieve()
                    .bodyToMono(List.class)
                    .timeout(Duration.ofSeconds(5))
                    .block();
        } catch (Exception e) {
            return List.of(
                    Map.of("id", "small_fast", "kind", "small_fast", "label", "Small Fast (2 Small Datasets)", "isDefault", true),
                    Map.of("id", "rag_ape", "kind", "rag_ape", "label", "RAG (APE)", "isDefault", false)
            );
        }
    }
}

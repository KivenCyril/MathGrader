package com.mathgrader.controller;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import com.mathgrader.service.QuestionPreprocessService;
import com.mathgrader.model.Submission;
import com.mathgrader.repository.SubmissionRepository;
import com.mathgrader.service.PythonAgentBridgeService;
import jakarta.transaction.Transactional;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.security.Principal;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/agent")
public class GradingController {
    private static final Logger log = LoggerFactory.getLogger(GradingController.class);

    private final PythonAgentBridgeService agentBridge;
    private final SubmissionRepository submissionRepository;
    private final QuestionPreprocessService preprocessService;

    public GradingController(
            PythonAgentBridgeService agentBridge,
            SubmissionRepository submissionRepository,
            QuestionPreprocessService preprocessService
    ) {
        this.agentBridge = agentBridge;
        this.submissionRepository = submissionRepository;
        this.preprocessService = preprocessService;
    }

    private long elapsedMs(long startedAtNanos) {
        return (System.nanoTime() - startedAtNanos) / 1_000_000;
    }

    private String newTraceId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }
    
    @PostMapping("/ocr")
    public Map<String, String> ocr(@RequestParam("file") MultipartFile file) {
        String traceId = newTraceId();
        long startedAt = System.nanoTime();
        log.info("[OCR][{}] request received file={} size={}B", traceId, file.getOriginalFilename(), file.getSize());
        Map<String, String> response = agentBridge.performOcr(file, traceId);
        log.info("[OCR][{}] completed in {} ms error={}", traceId, elapsedMs(startedAt), response.get("error"));
        return response;
    }
    
    @GetMapping("/models")
    public List<String> getModels() {
        return agentBridge.getAvailableModels();
    }

    @GetMapping("/grading-methods")
    public List<Map<String, Object>> getGradingMethods() {
        return agentBridge.getGradingMethods();
    }

    @PostMapping("/grade")
    public GradeResponse grade(@RequestBody GradeRequest request, Principal principal) {
        String traceId = newTraceId();
        long startedAt = System.nanoTime();
        long saveStartedAt = 0L;
        var preprocess = preprocessService.preprocess(
                request.getDatasetId(),
                request.getQuestionId(),
                request.getQuestionText(),
                request.getStandardAnswer()
        );
        request.setQuestionText(preprocess.normalizedQuestionText());
        request.setStandardAnswer(preprocess.normalizedTruth());
        if (request.getQuestionType() == null || request.getQuestionType().isBlank()) {
            request.setQuestionType(preprocess.questionType());
        }
        log.info(
                "[Grade][{}] request received user={} questionId={} datasetId={} type={} model={} tools={}",
                traceId,
                principal != null ? principal.getName() : "anonymous",
                request.getQuestionId(),
                request.getDatasetId(),
                request.getQuestionType(),
                request.getModel(),
                request.getEnableTools()
        );

        GradeResponse response = agentBridge.callPythonAgent(request, traceId);
        
        // Save submission to database
        try {
            saveStartedAt = System.nanoTime();
            Submission submission = new Submission();
            submission.setStudentName(principal != null ? principal.getName() : "anonymous");
            submission.setQuestionText(request.getQuestionText());
            submission.setStandardAnswer(request.getStandardAnswer());
            submission.setStudentAnswer(request.getStudentAnswer());
            String modelUsed = request.getModel() != null ? request.getModel() : "default";
            if (request.getGradingMethod() != null && !request.getGradingMethod().isBlank()) {
                modelUsed = modelUsed + "|" + request.getGradingMethod();
            }
            submission.setModelUsed(modelUsed);
            
            try {
                if (request.getMaxScore() != null && !request.getMaxScore().isEmpty()) {
                    submission.setMaxScore(Double.parseDouble(request.getMaxScore()));
                }
            } catch (NumberFormatException e) {
                // Ignore parsing error
                submission.setMaxScore(0);
            }

            if (response != null) {
                submission.setScore(response.getScore());
                submission.setCorrect(response.isCorrect());
                submission.setReason(response.getReason());
            }
            
            submissionRepository.save(submission);
        } catch (Exception e) {
            log.warn("[Grade][{}] submission save failed: {}", traceId, e.getMessage());
            // Continue even if save fails
        }
        long saveMs = saveStartedAt == 0L ? 0L : elapsedMs(saveStartedAt);
        log.info(
                "[Grade][{}] completed in {} ms saveMs={} correct={} score={}",
                traceId,
                elapsedMs(startedAt),
                saveMs,
                response != null && response.isCorrect(),
                response != null ? response.getScore() : null
        );
        
        return response;
    }
    
    @GetMapping("/history")
    public List<Submission> getHistory(Principal principal) {
        if (principal == null) return List.of();
        
        // If admin, return all
        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        if (auth != null && auth.getAuthorities().stream().anyMatch(a -> a.getAuthority().equals("ROLE_ADMIN"))) {
            return submissionRepository.findAllByOrderBySubmittedAtDesc();
        }
        
        return submissionRepository.findAllByStudentNameOrderBySubmittedAtDesc(principal.getName());
    }

    @DeleteMapping("/history")
    @Transactional
    public Map<String, Object> clearHistory(Principal principal) {
        if (principal == null) {
            return Map.of("ok", false, "deleted", 0, "scope", "none", "message", "Not authenticated");
        }

        Authentication auth = SecurityContextHolder.getContext().getAuthentication();
        boolean isAdmin = auth != null && auth.getAuthorities().stream().anyMatch(a -> a.getAuthority().equals("ROLE_ADMIN"));

        long deleted;
        String scope;
        if (isAdmin) {
            deleted = submissionRepository.count();
            submissionRepository.deleteAll();
            scope = "all";
        } else {
            deleted = submissionRepository.deleteByStudentName(principal.getName());
            scope = "self";
        }

        return Map.of("ok", true, "deleted", deleted, "scope", scope);
    }
    
    @PostMapping("/solve")
    public Map<String, Object> solve(@RequestBody Map<String, Object> payload) {
        String traceId = newTraceId();
        long startedAt = System.nanoTime();
        log.info("[Solve][{}] request received mode={} tools={}", traceId, payload.get("mode"), payload.get("enableTools"));
        Map<String, Object> response = agentBridge.solveQuestion(payload, traceId);
        log.info("[Solve][{}] completed in {} ms error={}", traceId, elapsedMs(startedAt), response.get("error"));
        return response;
    }
    
    @GetMapping("/health")
    public String health() {
        return "Java Web Backend is Running! Connected to Python Agent.";
    }
    
    @GetMapping("/me")
    public Map<String, String> me(Principal principal) {
        if (principal == null) return Map.of("username", "anonymous");
        return Map.of("username", principal.getName());
    }
}

package com.mathgrader.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import com.mathgrader.service.QuestionPreprocessService;
import com.mathgrader.model.Submission;
import com.mathgrader.repository.SubmissionRepository;
import com.mathgrader.service.GradeJobSessionService;
import com.mathgrader.service.PythonAgentBridgeService;
import com.mathgrader.service.RubricDocumentService;
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
    private final GradeJobSessionService gradeJobSessionService;
    private final RubricDocumentService rubricDocumentService;
    private final ObjectMapper objectMapper;

    public GradingController(
            PythonAgentBridgeService agentBridge,
            SubmissionRepository submissionRepository,
            QuestionPreprocessService preprocessService,
            GradeJobSessionService gradeJobSessionService,
            RubricDocumentService rubricDocumentService,
            ObjectMapper objectMapper
    ) {
        this.agentBridge = agentBridge;
        this.submissionRepository = submissionRepository;
        this.preprocessService = preprocessService;
        this.gradeJobSessionService = gradeJobSessionService;
        this.rubricDocumentService = rubricDocumentService;
        this.objectMapper = objectMapper;
    }

    private long elapsedMs(long startedAtNanos) {
        return (System.nanoTime() - startedAtNanos) / 1_000_000;
    }

    private String newTraceId() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    private void preprocessRequest(GradeRequest request) {
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
    }

    private void persistSubmission(GradeRequest request, GradeResponse response, String username) {
        Submission submission = new Submission();
        submission.setStudentName(username != null && !username.isBlank() ? username : "anonymous");
        submission.setQuestionText(request.getQuestionText());
        submission.setStandardAnswer(request.getStandardAnswer());
        submission.setStudentAnswer(request.getStudentAnswer());

        String modelUsed = "backend_default";
        submission.setModelUsed(modelUsed);

        try {
            if (request.getMaxScore() != null && !request.getMaxScore().isEmpty()) {
                submission.setMaxScore(Double.parseDouble(request.getMaxScore()));
            }
        } catch (NumberFormatException e) {
            submission.setMaxScore(0);
        }

        if (response != null) {
            submission.setScore(response.getScore());
            submission.setCorrect(response.isCorrect());
            submission.setReason(response.getReason());
        }

        submissionRepository.save(submission);
    }

    private void persistCompletedAsyncJobIfNeeded(String jobId, Map<String, Object> progressPayload) {
        if (jobId == null || jobId.isBlank() || progressPayload == null) {
            return;
        }
        String status = String.valueOf(progressPayload.getOrDefault("status", ""));
        if ("failed".equalsIgnoreCase(status)) {
            gradeJobSessionService.remove(jobId);
            return;
        }
        if (!"completed".equalsIgnoreCase(status)) {
            return;
        }

        GradeJobSessionService.PendingGradeSession session = gradeJobSessionService.get(jobId);
        if (session == null || session.isSaved()) {
            return;
        }

        Object rawResult = progressPayload.get("result");
        if (!(rawResult instanceof Map)) {
            return;
        }

        GradeResponse response = objectMapper.convertValue(rawResult, GradeResponse.class);
        persistSubmission(session.getRequest(), response, session.getUsername());
        session.markSaved();
        gradeJobSessionService.remove(jobId);
    }
    
    @PostMapping("/ocr")
    public Map<String, Object> ocr(@RequestParam("file") MultipartFile file) {
        String traceId = newTraceId();
        long startedAt = System.nanoTime();
        log.info("[OCR][{}] request received file={} size={}B", traceId, file.getOriginalFilename(), file.getSize());
        Map<String, Object> response = agentBridge.performOcr(file, traceId);
        log.info("[OCR][{}] completed in {} ms error={}", traceId, elapsedMs(startedAt), response.get("error"));
        return response;
    }

    @PostMapping("/rubric/extract")
    public Map<String, Object> extractRubric(@RequestParam("file") MultipartFile file) {
        String traceId = newTraceId();
        long startedAt = System.nanoTime();
        log.info("[Rubric][{}] extract request file={} size={}B", traceId, file.getOriginalFilename(), file.getSize());
        try {
            String text = rubricDocumentService.extractText(file);
            log.info("[Rubric][{}] extract completed in {} ms textLength={}", traceId, elapsedMs(startedAt), text.length());
            return Map.of(
                    "ok", true,
                    "traceId", traceId,
                    "fileName", String.valueOf(file.getOriginalFilename()),
                    "text", text
            );
        } catch (Exception e) {
            log.warn("[Rubric][{}] extract failed after {} ms: {}", traceId, elapsedMs(startedAt), e.getMessage());
            return Map.of(
                    "ok", false,
                    "traceId", traceId,
                    "error", "评分细则文件解析失败: " + e.getMessage()
            );
        }
    }
    
    @PostMapping("/grade")
    public GradeResponse grade(@RequestBody GradeRequest request, Principal principal) {
        String traceId = newTraceId();
        long startedAt = System.nanoTime();
        long saveStartedAt = 0L;
        preprocessRequest(request);
        log.info(
                "[Grade][{}] request received user={} questionId={} datasetId={} type={} tools={} needScore={} enableRecommendation={} scoringMode={} rubricJson={} rubricText={}",
                traceId,
                principal != null ? principal.getName() : "anonymous",
                request.getQuestionId(),
                request.getDatasetId(),
                request.getQuestionType(),
                request.getEnableTools(),
                request.getNeedScore(),
                request.getEnableRecommendation(),
                request.getScoringMode(),
                request.getRubricJson() != null,
                request.getRubricText() != null && !request.getRubricText().isBlank()
        );

        GradeResponse response = agentBridge.callPythonAgent(request, traceId);
        
        // Save submission to database
        try {
            saveStartedAt = System.nanoTime();
            persistSubmission(request, response, principal != null ? principal.getName() : "anonymous");
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

    @PostMapping("/grade/submit")
    public Map<String, Object> submitGrade(@RequestBody GradeRequest request, Principal principal) {
        String traceId = newTraceId();
        preprocessRequest(request);
        log.info(
                "[Grade][{}] async request received user={} questionId={} datasetId={} type={} tools={} needScore={} enableRecommendation={} scoringMode={} rubricJson={} rubricText={}",
                traceId,
                principal != null ? principal.getName() : "anonymous",
                request.getQuestionId(),
                request.getDatasetId(),
                request.getQuestionType(),
                request.getEnableTools(),
                request.getNeedScore(),
                request.getEnableRecommendation(),
                request.getScoringMode(),
                request.getRubricJson() != null,
                request.getRubricText() != null && !request.getRubricText().isBlank()
        );
        Map<String, Object> accepted = agentBridge.submitGradeJob(request, traceId);
        String jobId = String.valueOf(accepted.getOrDefault("jobId", ""));
        if (jobId != null && !jobId.isBlank()) {
            gradeJobSessionService.register(jobId, traceId, request, principal != null ? principal.getName() : "anonymous");
        }
        return accepted;
    }

    @GetMapping("/grade/progress/{jobId}")
    public Map<String, Object> gradeProgress(@PathVariable String jobId) {
        String traceId = newTraceId();
        Map<String, Object> progress = agentBridge.fetchGradeJobProgress(jobId, traceId);
        try {
            persistCompletedAsyncJobIfNeeded(jobId, progress);
        } catch (Exception e) {
            log.warn("[Grade][{}] async submission save failed for job {}: {}", traceId, jobId, e.getMessage());
        }
        return progress;
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

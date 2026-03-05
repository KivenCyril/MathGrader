package com.mathgrader.controller;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import com.mathgrader.model.Submission;
import com.mathgrader.repository.SubmissionRepository;
import com.mathgrader.service.PythonAgentBridgeService;
import jakarta.transaction.Transactional;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.bind.annotation.*;

import java.security.Principal;
import java.util.List;
import java.util.Map;

import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/agent")
public class GradingController {

    private final PythonAgentBridgeService agentBridge;
    private final SubmissionRepository submissionRepository;

    public GradingController(PythonAgentBridgeService agentBridge, SubmissionRepository submissionRepository) {
        this.agentBridge = agentBridge;
        this.submissionRepository = submissionRepository;
    }
    
    @PostMapping("/ocr")
    public Map<String, String> ocr(@RequestParam("file") MultipartFile file) {
        return agentBridge.performOcr(file);
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
        GradeResponse response = agentBridge.callPythonAgent(request);
        
        // Save submission to database
        try {
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
            e.printStackTrace();
            // Continue even if save fails
        }
        
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
    public Map<String, String> solve(@RequestBody Map<String, Object> payload) {
        return agentBridge.solveQuestion(payload);
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

package com.mathgrader.controller;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import com.mathgrader.service.PythonAgentBridgeService;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.Map;

import org.springframework.web.multipart.MultipartFile;

@RestController
@RequestMapping("/api/agent")
@CrossOrigin(origins = "*")
public class GradingController {

    private final PythonAgentBridgeService agentBridge;

    public GradingController(PythonAgentBridgeService agentBridge) {
        this.agentBridge = agentBridge;
    }
    
    @PostMapping("/ocr")
    public Map<String, String> ocr(@RequestParam("file") MultipartFile file) {
        return agentBridge.performOcr(file);
    }
    
    @GetMapping("/models")
    public List<String> getModels() {
        return agentBridge.getAvailableModels();
    }

    @PostMapping("/grade")
    public GradeResponse grade(@RequestBody GradeRequest request) {
        return agentBridge.callPythonAgent(request);
    }
    
    @PostMapping("/solve")
    public Map<String, String> solve(@RequestBody Map<String, Object> payload) {
        return agentBridge.solveQuestion(payload);
    }
    
    @GetMapping("/health")
    public String health() {
        return "Java Web Backend is Running! Connected to Python Agent.";
    }
}

package com.mathgrader.controller;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import com.mathgrader.service.PythonAgentBridgeService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/agent")
@CrossOrigin(origins = "*")
public class GradingController {

    private final PythonAgentBridgeService agentBridge;

    public GradingController(PythonAgentBridgeService agentBridge) {
        this.agentBridge = agentBridge;
    }

    @PostMapping("/grade")
    public GradeResponse grade(@RequestBody GradeRequest request) {
        // Forward logic to Python Bridge
        return agentBridge.callPythonAgent(request);
    }
    
    @GetMapping("/health")
    public String health() {
        return "Java Web Backend is Running! Connected to Python Agent.";
    }
}

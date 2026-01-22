package com.mathgrader.controller;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import com.mathgrader.service.AgentService;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/agent")
@CrossOrigin(origins = "*") // Allow frontend to call
public class GradingController {

    private final AgentService agentService;

    public GradingController(AgentService agentService) {
        this.agentService = agentService;
    }

    @PostMapping("/grade")
    public GradeResponse grade(@RequestBody GradeRequest request) {
        return agentService.grade(request);
    }
    
    @GetMapping("/health")
    public String health() {
        return "Java Agent is Running!";
    }
}

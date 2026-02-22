package com.mathgrader.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mathgrader.service.FileService;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

import java.util.stream.Collectors;

@RestController
@RequestMapping("/api")
public class DatasetController {

    private final FileService fileService;
    private final ObjectMapper mapper = new ObjectMapper();

    public DatasetController(FileService fileService) {
        this.fileService = fileService;
    }

    @GetMapping("/datasets")
    public List<Map<String, String>> list() {
        return fileService.listDatasets();
    }
    
    @GetMapping("/levels")
    public List<String> getLevels(@RequestParam String id) {
        try {
            List<Map<String, Object>> raw = fileService.loadAndParse(id);
            return raw.stream()
                .map(item -> findField(item, "level", "grade"))
                .filter(s -> !s.isEmpty())
                .distinct()
                .sorted()
                .collect(Collectors.toList());
        } catch (Exception e) {
            return new ArrayList<>();
        }
    }

    @GetMapping("/load")
    public List<Map<String, Object>> load(@RequestParam String id, @RequestParam(required = false) String level) {
        try {
            List<Map<String, Object>> raw = fileService.loadAndParse(id);
            
            // Filter by level if provided
            if (level != null && !level.isEmpty()) {
                raw = raw.stream()
                    .filter(item -> {
                        String l = findField(item, "level", "grade");
                        return level.equals(l);
                    })
                    .collect(Collectors.toList());
            }
            
            // Transform to frontend format
            List<Map<String, Object>> result = new ArrayList<>();
            for (int i = 0; i < raw.size(); i++) {
                Map<String, Object> item = raw.get(i);
                
                String qText = findField(item, "original_text", "text", "question", "problem", "body");
                String qTruth = findField(item, "ans", "answer", "truth", "correct_answer", "solution");
                String qId = findField(item, "id", "problem_id", "_id");
                if (qId.isEmpty()) qId = String.valueOf(i + 1);
                
                String eq = findField(item, "equation", "formula");
                
                Map<String, Object> q = Map.of(
                    "id", qId,
                    "text", qText,
                    "truth", qTruth,
                    "meta", eq.isEmpty() ? "Unknown Source" : "Equation: " + eq,
                    "maxScore", 1
                );
                result.add(q);
            }
            return result;
        } catch (Exception e) {
            throw new RuntimeException("Load failed: " + e.getMessage());
        }
    }
    
    private String findField(Map<String, Object> item, String... keys) {
        for (String key : keys) {
            if (item.containsKey(key)) return String.valueOf(item.get(key));
        }
        // Fallback: Case insensitive search
        for (String key : item.keySet()) {
            for (String target : keys) {
                if (key.equalsIgnoreCase(target)) return String.valueOf(item.get(key));
            }
        }
        return "";
    }
}

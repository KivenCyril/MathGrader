package com.mathgrader.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mathgrader.service.FileService;
import com.mathgrader.service.QuestionPreprocessService;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import java.util.stream.Collectors;

@RestController
@RequestMapping("/api")
public class DatasetController {

    private final FileService fileService;
    private final QuestionPreprocessService preprocessService;
    private final ObjectMapper mapper = new ObjectMapper();

    public DatasetController(FileService fileService, QuestionPreprocessService preprocessService) {
        this.fileService = fileService;
        this.preprocessService = preprocessService;
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
    public Object load(
            @RequestParam String id,
            @RequestParam(required = false) String level,
            @RequestParam(required = false) Integer page,
            @RequestParam(required = false) Integer pageSize) {
        try {
            List<Map<String, Object>> raw = fileService.loadAndParse(id);

            if (level != null && !level.isEmpty()) {
                raw = raw.stream()
                    .filter(item -> {
                        String l = findField(item, "level", "grade");
                        return level.equals(l);
                    })
                    .collect(Collectors.toList());
            }

            if (page == null || pageSize == null) {
                return transformItems(id, raw, 0, raw.size());
            }

            int safePage = Math.max(0, page);
            int safePageSize = Math.max(1, pageSize);
            int start = Math.min(safePage * safePageSize, raw.size());
            int end = Math.min(start + safePageSize, raw.size());

            Map<String, Object> response = new HashMap<>();
            response.put("items", transformItems(id, raw, start, end));
            response.put("total", raw.size());
            response.put("page", safePage);
            response.put("pageSize", safePageSize);
            return response;
        } catch (Exception e) {
            throw new RuntimeException("Load failed: " + e.getMessage());
        }
    }

    private List<Map<String, Object>> transformItems(String datasetId, List<Map<String, Object>> raw, int start, int end) {
        List<Map<String, Object>> result = new ArrayList<>();
        for (int i = start; i < end; i++) {
            Map<String, Object> item = raw.get(i);

            String qText = findField(item, "original_text", "text", "question", "problem", "body");
            String qTruth = findField(item, "ans", "answer", "truth", "correct_answer", "solution");
            String qId = findField(item, "id", "problem_id", "_id");
            if (qId.isEmpty()) qId = String.valueOf(i + 1);

            String eq = findField(item, "equation", "formula");

            Map<String, Object> q = new HashMap<>(Map.of(
                "id", qId,
                "text", qText,
                "truth", qTruth,
                "meta", eq.isEmpty() ? "Unknown Source" : "Equation: " + eq,
                "maxScore", 1
            ));
            preprocessService.applyToDatasetItem(datasetId, qId, q);
            result.add(q);
        }
        return result;
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

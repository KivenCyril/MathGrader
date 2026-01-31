package com.mathgrader.controller;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.mathgrader.service.FileService;
import org.springframework.web.bind.annotation.*;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/api")
@CrossOrigin(origins = "*")
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

    @GetMapping("/load")
    public List<Map<String, Object>> load(@RequestParam String id) {
        try {
            String json = fileService.loadDataset(id);
            // Parse raw json
            List<Map<String, Object>> raw = mapper.readValue(json, new TypeReference<List<Map<String, Object>>>(){});
            
            // Transform to frontend format
            List<Map<String, Object>> result = new ArrayList<>();
            for (int i = 0; i < raw.size(); i++) {
                Map<String, Object> item = raw.get(i);
                Map<String, Object> q = Map.of(
                    "id", item.getOrDefault("id", String.valueOf(i)),
                    "text", item.getOrDefault("original_text", item.getOrDefault("text", "")),
                    "truth", item.getOrDefault("ans", item.getOrDefault("answer", "")),
                    "meta", "Math23K (Eq: " + item.getOrDefault("equation", "") + ")",
                    "maxScore", 1
                );
                result.add(q);
            }
            return result;
        } catch (Exception e) {
            throw new RuntimeException("Load failed: " + e.getMessage());
        }
    }
}

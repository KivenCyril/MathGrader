package com.mathgrader.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.MappingIterator;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.stream.Stream;

@Service
public class FileService {
    private final Map<String, List<Map<String, Object>>> datasetCache = new ConcurrentHashMap<>();

    @Value("${app.data.root:}")
    private String dataRoot;

    // Resolve dataset root in a portable way.
    // Priority: app.data.root -> ../data/raw -> data/raw
    private Path getDataRoot() {
        if (dataRoot != null && !dataRoot.isBlank()) {
            Path configured = Paths.get(dataRoot);
            if (Files.exists(configured)) return configured;
        }

        Path p1 = Paths.get("../data/raw");
        if (Files.exists(p1)) return p1;

        Path p2 = Paths.get("data/raw");
        if (Files.exists(p2)) return p2;

        // Fallback to current working directory + data/raw for safer error messages
        return Paths.get(System.getProperty("user.dir"), "data", "raw");
    }

    private final ObjectMapper mapper = new ObjectMapper();

    public List<Map<String, String>> listDatasets() {
        Path root = getDataRoot();
        List<Map<String, String>> datasets = new ArrayList<>();
        if (!Files.exists(root)) {
            System.err.println("Data root not found: " + root.toAbsolutePath());
            return datasets;
        }

        try (Stream<Path> paths = Files.walk(root)) {
            paths.filter(Files::isRegularFile)
                 .filter(p -> p.toString().endsWith(".json") || p.toString().endsWith(".jsonl"))
                 .filter(p -> {
                     // Exclude files with keywords like 'common', 'shot' in filename (case insensitive)
                     // Also exclude files in 'evaluation' or 'results' directories
                     String pathStr = p.toString().toLowerCase();
                     String fileName = p.getFileName().toString().toLowerCase();
                     
                     // 1. Exclude directory names
                    if (pathStr.contains("evaluation") || pathStr.contains("results") || pathStr.contains("images") || pathStr.contains("outputs")) return false;
                    
                    // 2. Exclude filename patterns
                    // Exclude 'all_data.jsonl' as it duplicates other files
                    if (fileName.contains("shot") || fileName.contains("common") || fileName.contains("result") || fileName.equals("all_data.jsonl")) return false;
                     
                     return true;
                 })
                 .forEach(p -> {
                     Map<String, String> map = new HashMap<>();
                     String rel = root.relativize(p).toString().replace("\\", "/");
                     map.put("id", rel);
                     map.put("name", p.getFileName().toString());
                     map.put("group", p.getParent().getFileName().toString());
                     datasets.add(map);
                 });
        } catch (IOException e) {
            e.printStackTrace();
        }
        return datasets;
    }

    public List<Map<String, Object>> loadAndParse(String id) throws IOException {
        List<Map<String, Object>> cached = datasetCache.get(id);
        if (cached != null) {
            return cached;
        }

        Path root = getDataRoot();
        Path file = root.resolve(id);
        if (!Files.exists(file)) throw new IOException("File not found: " + id);

        List<Map<String, Object>> rawData = new ArrayList<>();

        // Best approach: Use MappingIterator to read concatenated JSON objects (JSONL)
        try (MappingIterator<Map<String, Object>> it = mapper.readerFor(Map.class).readValues(file.toFile())) {
             while (it.hasNext()) {
                rawData.add(it.next());
            }
        } catch (Exception e) {
            // Fallback: Try reading as a standard JSON Array
            try {
                rawData = mapper.readValue(file.toFile(), new TypeReference<List<Map<String, Object>>>(){});
            } catch (Exception ex) {
                 throw new IOException("Failed to parse dataset: " + e.getMessage() + " | " + ex.getMessage());
            }
        }
        
        // Normalize fields
        for (Map<String, Object> item : rawData) {
            // Map 'question' to 'text'
            if (!item.containsKey("text") && item.containsKey("question")) {
                item.put("text", item.get("question"));
            }
            // Map 'answer' to 'truth'
            if (!item.containsKey("truth") && item.containsKey("answer")) {
                item.put("truth", item.get("answer"));
            }
            // Append options to text if present
            if (item.containsKey("options") && item.get("options") != null) {
                Object qObj = item.get("text");
                String q = qObj != null ? qObj.toString() : "";
                String opts = item.get("options").toString();
                // Avoid double appending if already present
                if (!q.contains(opts)) {
                    item.put("text", q + "\n\n" + opts);
                }
            }
            // Add 'meta' info
            if (!item.containsKey("meta")) {
                StringBuilder meta = new StringBuilder();
                if (item.containsKey("level")) meta.append(item.get("level")).append(" ");
                if (item.containsKey("subject")) meta.append(item.get("subject"));
                item.put("meta", meta.toString().trim());
            }
        }
        
        datasetCache.put(id, rawData);
        return rawData;
    }
}

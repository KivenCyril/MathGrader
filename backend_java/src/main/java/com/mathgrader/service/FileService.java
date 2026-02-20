package com.mathgrader.service;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.MappingIterator;
import com.fasterxml.jackson.databind.ObjectMapper;
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
import java.util.stream.Stream;

@Service
public class FileService {

    // Use absolute path to avoid CWD issues
    // Assuming the structure is fixed relative to backend_java or project root
    // But since we are running from backend_java folder (via mvn), ".." goes to project root.
    // However, let's try to be more robust by checking if "../data/raw" exists, if not try "data/raw" (if running from root)
    private Path getDataRoot() {
        Path p1 = Paths.get("../data/raw");
        if (Files.exists(p1)) return p1;
        Path p2 = Paths.get("data/raw");
        if (Files.exists(p2)) return p2;
        // Absolute fallback for dev environment
        return Paths.get("E:/test/Pywork/math_grader/data/raw");
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
                     if (pathStr.contains("evaluation") || pathStr.contains("results") || pathStr.contains("images")) return false;
                     
                     // 2. Exclude filename patterns (e.g. shot, common, result) which are likely intermediate files or prompts
                     if (fileName.contains("shot") || fileName.contains("common") || fileName.contains("result")) return false;
                     
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
        Path root = getDataRoot();
        Path file = root.resolve(id);
        if (!Files.exists(file)) throw new IOException("File not found: " + id);

        // Best approach: Use MappingIterator to read concatenated JSON objects
        try (MappingIterator<Map<String, Object>> it = mapper.readerFor(Map.class).readValues(file.toFile())) {
            return it.readAll();
        } catch (Exception e) {
            // Fallback: Try reading as a standard JSON Array
            try {
                return mapper.readValue(file.toFile(), new TypeReference<List<Map<String, Object>>>(){});
            } catch (Exception ex) {
                 throw new IOException("Failed to parse dataset: " + e.getMessage() + " | " + ex.getMessage());
            }
        }
    }
}

package com.mathgrader.service;

import com.fasterxml.jackson.core.type.TypeReference;
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

    private final Path DATA_ROOT = Paths.get("../data/raw"); 
    private final ObjectMapper mapper = new ObjectMapper();

    public List<Map<String, String>> listDatasets() {
        List<Map<String, String>> datasets = new ArrayList<>();
        if (!Files.exists(DATA_ROOT)) return datasets;

        try (Stream<Path> paths = Files.walk(DATA_ROOT)) {
            paths.filter(Files::isRegularFile)
                 .filter(p -> p.toString().endsWith(".json"))
                 .forEach(p -> {
                     Map<String, String> map = new HashMap<>();
                     String rel = DATA_ROOT.relativize(p).toString().replace("\\", "/");
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
        Path file = DATA_ROOT.resolve(id);
        if (!Files.exists(file)) throw new IOException("File not found: " + id);

        // Try 1: Read as full JSON array
        try {
            return mapper.readValue(file.toFile(), new TypeReference<List<Map<String, Object>>>(){});
        } catch (Exception e) {
            // Try 2: JSONL (Line-by-line)
            List<Map<String, Object>> result = new ArrayList<>();
            try (BufferedReader reader = Files.newBufferedReader(file)) {
                String line;
                while ((line = reader.readLine()) != null) {
                    line = line.trim();
                    if (line.isEmpty()) continue;
                    try {
                        Map<String, Object> obj = mapper.readValue(line, new TypeReference<Map<String, Object>>(){});
                        result.add(obj);
                    } catch (Exception ignored) {
                        // Skip bad lines
                    }
                }
            }
            if (result.isEmpty()) {
                // If both failed, maybe it's the "consecutive objects" format without newlines?
                // Try reading full content and fixing it
                String content = Files.readString(file).trim();
                // Naive fix: } { -> }, {
                content = "[" + content.replace("}{", "},{").replace("}\n{", "},{") + "]";
                try {
                    return mapper.readValue(content, new TypeReference<List<Map<String, Object>>>(){});
                } catch (Exception ex) {
                    throw new IOException("Failed to parse dataset. Tried Array, JSONL, and Naive Fix.");
                }
            }
            return result;
        }
    }
}

package com.mathgrader.service;

import org.springframework.stereotype.Service;

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

    // Hardcoded path for now, should be config
    private final Path DATA_ROOT = Paths.get("../data/raw"); 

    public List<Map<String, String>> listDatasets() {
        List<Map<String, String>> datasets = new ArrayList<>();
        if (!Files.exists(DATA_ROOT)) return datasets;

        try (Stream<Path> paths = Files.walk(DATA_ROOT)) {
            paths.filter(Files::isRegularFile)
                 .filter(p -> p.toString().endsWith(".json"))
                 .forEach(p -> {
                     Map<String, String> map = new HashMap<>();
                     // Create relative ID
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

    public String loadDataset(String id) throws IOException {
        Path file = DATA_ROOT.resolve(id);
        if (!Files.exists(file)) {
            throw new IOException("File not found: " + id);
        }
        // Just read raw content for now, parsing logic is duplicated from Python's math23k.py?
        // Actually, Python's loader logic was a bit complex (fixing json).
        // Let's implement a simple fixer here similar to Python's load_math23k
        
        String content = Files.readString(file);
        // Fix {..}{..} -> [{..},{..}] if needed
        if (!content.trim().startsWith("[")) {
             content = "[" + content.replace("}\n{", "},{") + "]";
        }
        return content;
    }
}

package com.mathgrader.model;

import lombok.Data;

import java.util.List;
import java.util.Map;

@Data
public class GradeResponse {
    private boolean correct;
    private double score;
    private String reason;
    private String usage; // Token usage info
    private String methodUsed;
    private Map<String, Object> details;
    private Map<String, Object> scoring;
    private Map<String, Object> comparison;
    private List<Map<String, Object>> similarQuestions;
    private Map<String, Object> retrieval;
}

package com.mathgrader.model;

import lombok.Data;

import java.util.List;

@Data
public class GradeRequest {
    private String questionText;
    private String standardAnswer;
    private String studentAnswer;
    private String maxScore;
    private String mode; // "single" or "review"
    private String model; // e.g. "qwen", "deepseek"
    private String gradingMethod; // e.g. "small_fast", "rag_ape"
    private List<String> compareMethods; // optional A/B comparison
    private String datasetId; // for retrieval from local dataset
    private String level;
    private String questionId;
    private Integer recommendationCount;
    private Integer retrievalTopK;
    private Boolean enableTools;
}

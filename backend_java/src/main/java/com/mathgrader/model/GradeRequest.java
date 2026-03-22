package com.mathgrader.model;

import lombok.Data;

import java.util.Map;

@Data
public class GradeRequest {
    private String questionText;
    private String standardAnswer;
    private String studentAnswer;
    private String maxScore;
    private String mode; // "single" or "review"
    private String datasetId; // for retrieval from local dataset
    private String level;
    private String questionId;
    private String questionType;
    private Integer recommendationCount;
    private Integer retrievalTopK;
    private Boolean enableRecommendation;
    private Boolean enableTools;
    private Boolean needScore;
    private String scoringMode;
    private Map<String, Object> rubricJson;
    private String rubricText;
}

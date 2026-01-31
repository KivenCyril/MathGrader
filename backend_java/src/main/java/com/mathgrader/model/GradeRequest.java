package com.mathgrader.model;

import lombok.Data;

@Data
public class GradeRequest {
    private String questionText;
    private String standardAnswer;
    private String studentAnswer;
    private String maxScore;
    private String mode; // "single" or "review"
}

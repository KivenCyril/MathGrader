package com.mathgrader.model;

import lombok.Data;

@Data
public class GradeResponse {
    private boolean correct;
    private double score;
    private String reason;
    private String usage; // Token usage info
}

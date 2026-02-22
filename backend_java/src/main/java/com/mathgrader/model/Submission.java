package com.mathgrader.model;

import jakarta.persistence.*;
import lombok.Data;
import java.time.LocalDateTime;

@Entity
@Data
public class Submission {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String studentName; // Currently null or placeholder

    @Column(columnDefinition = "TEXT")
    private String questionText;

    @Column(columnDefinition = "TEXT")
    private String standardAnswer;

    @Column(columnDefinition = "TEXT")
    private String studentAnswer;

    private double score;
    private double maxScore;

    @Column(columnDefinition = "TEXT")
    private String reason;

    private boolean correct;
    
    private String modelUsed;

    private LocalDateTime submittedAt;

    @PrePersist
    protected void onCreate() {
        submittedAt = LocalDateTime.now();
    }
}

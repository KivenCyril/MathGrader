package com.mathgrader.model;

import jakarta.persistence.*;
import lombok.Data;

import java.time.LocalDateTime;

@Entity
@Table(
        name = "question_preprocess",
        uniqueConstraints = {
                @UniqueConstraint(name = "uk_dataset_question", columnNames = {"datasetId", "questionId"})
        }
)
@Data
public class QuestionPreprocess {
    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    private String datasetId;

    private String questionId;

    @Column(columnDefinition = "TEXT")
    private String rawQuestionText;

    @Column(columnDefinition = "TEXT")
    private String normalizedQuestionText;

    @Column(columnDefinition = "TEXT")
    private String rawTruth;

    @Column(columnDefinition = "TEXT")
    private String normalizedTruth;

    private String questionType;

    private String cleanStatus;

    private String cleanVersion;

    private LocalDateTime createdAt;

    private LocalDateTime updatedAt;

    @PrePersist
    protected void onCreate() {
        LocalDateTime now = LocalDateTime.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = LocalDateTime.now();
    }
}

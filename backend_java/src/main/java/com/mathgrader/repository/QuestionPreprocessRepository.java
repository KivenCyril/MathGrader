package com.mathgrader.repository;

import com.mathgrader.model.QuestionPreprocess;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.Optional;

@Repository
public interface QuestionPreprocessRepository extends JpaRepository<QuestionPreprocess, Long> {
    Optional<QuestionPreprocess> findByDatasetIdAndQuestionId(String datasetId, String questionId);
}

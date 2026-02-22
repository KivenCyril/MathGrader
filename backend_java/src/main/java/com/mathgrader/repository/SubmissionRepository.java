package com.mathgrader.repository;

import com.mathgrader.model.Submission;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface SubmissionRepository extends JpaRepository<Submission, Long> {
    List<Submission> findAllByOrderBySubmittedAtDesc();
    List<Submission> findAllByStudentNameOrderBySubmittedAtDesc(String studentName);
}

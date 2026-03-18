package com.mathgrader.service;

import com.mathgrader.model.QuestionPreprocess;
import com.mathgrader.repository.QuestionPreprocessRepository;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.Optional;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

@Service
public class QuestionPreprocessService {
    private static final Pattern MIXED_FRACTION = Pattern.compile("(\\d+)\\((\\d+\\s*/\\s*\\d+)\\)");
    private static final Pattern CHOICE_PATTERN = Pattern.compile("^[\\(\\[（\\s]*([A-F])[\\)\\]）\\.\\s]*$");

    private final QuestionPreprocessRepository repository;

    public QuestionPreprocessService(QuestionPreprocessRepository repository) {
        this.repository = repository;
    }

    public QuestionPreprocessResult preprocess(String datasetId, String questionId, String questionText, String truth) {
        Optional<QuestionPreprocess> existing = findExisting(datasetId, questionId);
        if (existing.isPresent()) {
            QuestionPreprocess row = existing.get();
            return new QuestionPreprocessResult(
                    nullToEmpty(row.getRawQuestionText()),
                    firstNonBlank(row.getNormalizedQuestionText(), questionText),
                    nullToEmpty(row.getRawTruth()),
                    firstNonBlank(row.getNormalizedTruth(), truth),
                    firstNonBlank(row.getQuestionType(), inferQuestionType(questionText, truth))
            );
        }

        String rawQuestion = nullToEmpty(questionText);
        String rawTruth = nullToEmpty(truth);
        String normalizedQuestion = normalizeQuestionText(rawQuestion);
        String normalizedTruth = normalizeAnswerText(rawTruth);
        String questionType = inferQuestionType(normalizedQuestion, normalizedTruth);

        if (isPersistable(datasetId, questionId)) {
            QuestionPreprocess row = new QuestionPreprocess();
            row.setDatasetId(datasetId);
            row.setQuestionId(questionId);
            row.setRawQuestionText(rawQuestion);
            row.setNormalizedQuestionText(normalizedQuestion);
            row.setRawTruth(rawTruth);
            row.setNormalizedTruth(normalizedTruth);
            row.setQuestionType(questionType);
            row.setCleanStatus("done");
            row.setCleanVersion("v1");
            repository.save(row);
        }

        return new QuestionPreprocessResult(rawQuestion, normalizedQuestion, rawTruth, normalizedTruth, questionType);
    }

    public Map<String, Object> applyToDatasetItem(String datasetId, String questionId, Map<String, Object> item) {
        String questionText = String.valueOf(item.getOrDefault("text", ""));
        String truth = String.valueOf(item.getOrDefault("truth", ""));
        QuestionPreprocessResult result = preprocess(datasetId, questionId, questionText, truth);
        item.put("text", result.normalizedQuestionText());
        item.put("truth", result.normalizedTruth());
        item.put("questionType", result.questionType());
        return item;
    }

    public String normalizeQuestionText(String input) {
        String s = nullToEmpty(input).trim();
        if (s.isEmpty()) return s;
        s = s
                .replace('\uFF08', '(')
                .replace('\uFF09', ')')
                .replace('\u3002', '.')
                .replace('\uFF0E', '.')
                .replace('\uFF0B', '+')
                .replace('\uFF0D', '-')
                .replace('\u00D7', '*')
                .replace('\u00F7', '/')
                .replace('\u2212', '-')
                .replace('[', '(')
                .replace(']', ')')
                .replace('{', '(')
                .replace('}', ')');
        s = s.replaceAll("[\\t\\r\\f]+", " ");
        s = s.replaceAll("[ ]{2,}", " ");
        return s.strip();
    }

    public String normalizeAnswerText(String input) {
        return normalizeQuestionText(input);
    }

    public String inferQuestionType(String questionText, String truth) {
        String normalizedTruth = normalizeAnswerText(truth).trim();
        String judgment = normalizeJudgmentAnswer(normalizedTruth);
        if (!judgment.isEmpty()) return "judgment";
        String choice = normalizeChoiceAnswer(normalizedTruth);
        if (!choice.isEmpty()) return "choice";
        if (looksLikeArithmetic(questionText)) return "arithmetic";
        return "complex";
    }

    private boolean looksLikeArithmetic(String text) {
        String normalized = normalizeQuestionText(text).replace(" ", "");
        if (normalized.isEmpty()) return false;
        if (normalized.matches(".*[A-Za-z\\u4e00-\\u9fff].*")) return false;
        normalized = MIXED_FRACTION.matcher(normalized).replaceAll("($1+$2)");
        return normalized.matches("[0-9\\.\\+\\-\\*/\\(\\)=]+") && normalized.matches(".*[\\+\\-\\*/].*");
    }

    private String normalizeChoiceAnswer(String input) {
        Matcher matcher = CHOICE_PATTERN.matcher(nullToEmpty(input).trim().toUpperCase());
        return matcher.matches() ? matcher.group(1) : "";
    }

    private String normalizeJudgmentAnswer(String input) {
        String s = nullToEmpty(input).trim().toLowerCase();
        return switch (s) {
            case "true", "t", "yes", "1", "对", "正确", "√" -> "true";
            case "false", "f", "no", "0", "错", "错误", "×" -> "false";
            default -> "";
        };
    }

    private Optional<QuestionPreprocess> findExisting(String datasetId, String questionId) {
        if (!isPersistable(datasetId, questionId)) {
            return Optional.empty();
        }
        return repository.findByDatasetIdAndQuestionId(datasetId, questionId);
    }

    private boolean isPersistable(String datasetId, String questionId) {
        return datasetId != null && !datasetId.isBlank() && questionId != null && !questionId.isBlank();
    }

    private String nullToEmpty(String value) {
        return value == null ? "" : value;
    }

    private String firstNonBlank(String preferred, String fallback) {
        return (preferred != null && !preferred.isBlank()) ? preferred : nullToEmpty(fallback);
    }

    public record QuestionPreprocessResult(
            String rawQuestionText,
            String normalizedQuestionText,
            String rawTruth,
            String normalizedTruth,
            String questionType
    ) {}
}

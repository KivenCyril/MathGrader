package com.mathgrader.service;

import com.mathgrader.model.GradeRequest;
import com.mathgrader.model.GradeResponse;
import dev.langchain4j.model.chat.ChatLanguageModel;
import dev.langchain4j.model.output.Response;
import dev.langchain4j.service.AiServices;
import dev.langchain4j.service.SystemMessage;
import dev.langchain4j.service.UserMessage;
import dev.langchain4j.service.V;
import org.springframework.stereotype.Service;

@Service
public class AgentService {

    private final ChatLanguageModel chatLanguageModel;

    // Define the interface for the AI Service
    interface MathGraderAgent {
        @SystemMessage("你是一个专业的小学数学阅卷老师。你的任务是根据题目、标准答案和学生答案，判断学生是否正确，并给出评分理由。")
        @UserMessage("题目：{{q}}\n" +
                "标准答案：{{truth}}\n" +
                "学生答案：{{student}}\n" +
                "本题满分：{{maxScore}}\n" +
                "\n" +
                "请严格按照以下JSON格式返回结果（不要返回其他文字）：\n" +
                "{\n" +
                "    \"correct\": boolean,\n" +
                "    \"score\": number,\n" +
                "    \"reason\": \"简短的评语\"\n" +
                "}")
        String grade(@V("q") String question, 
                     @V("truth") String truth, 
                     @V("student") String student,
                     @V("maxScore") String maxScore);
    }

    private final MathGraderAgent agent;

    public AgentService(ChatLanguageModel chatLanguageModel) {
        this.chatLanguageModel = chatLanguageModel;
        this.agent = AiServices.create(MathGraderAgent.class, chatLanguageModel);
    }

    public GradeResponse grade(GradeRequest request) {
        try {
            String jsonResult = agent.grade(
                request.getQuestionText(), 
                request.getStandardAnswer(), 
                request.getStudentAnswer(), 
                request.getMaxScore()
            );
            
            // Simple parsing (in production, use Jackson)
            // Assuming the LLM returns valid JSON as requested.
            // We'll clean it up just in case it wraps in markdown blocks
            String cleanJson = jsonResult.replace("```json", "").replace("```", "").trim();
            
            com.fasterxml.jackson.databind.ObjectMapper mapper = new com.fasterxml.jackson.databind.ObjectMapper();
            GradeResponse response = mapper.readValue(cleanJson, GradeResponse.class);
            return response;
            
        } catch (Exception e) {
            GradeResponse error = new GradeResponse();
            error.setReason("AI 判卷失败: " + e.getMessage());
            error.setCorrect(false);
            error.setScore(0);
            return error;
        }
    }
}

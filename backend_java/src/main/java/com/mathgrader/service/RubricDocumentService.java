package com.mathgrader.service;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;
import org.apache.poi.hwpf.HWPFDocument;
import org.apache.poi.hwpf.extractor.WordExtractor;
import org.apache.poi.xwpf.usermodel.XWPFDocument;
import org.apache.poi.xwpf.extractor.XWPFWordExtractor;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.util.Locale;

@Service
public class RubricDocumentService {
    public String extractText(MultipartFile file) throws IOException {
        if (file == null || file.isEmpty()) {
            throw new IOException("上传文件为空");
        }

        String filename = file.getOriginalFilename();
        String extension = extensionOf(filename);
        byte[] bytes = file.getBytes();

        return switch (extension) {
            case "txt", "json" -> new String(bytes, StandardCharsets.UTF_8).strip();
            case "pdf" -> extractPdf(bytes);
            case "docx" -> extractDocx(bytes);
            case "doc" -> extractDoc(bytes);
            default -> throw new IOException("暂不支持的评分细则文件类型: " + extension);
        };
    }

    private String extractPdf(byte[] bytes) throws IOException {
        try (PDDocument document = Loader.loadPDF(bytes)) {
            PDFTextStripper stripper = new PDFTextStripper();
            return stripper.getText(document).strip();
        }
    }

    private String extractDocx(byte[] bytes) throws IOException {
        try (
                InputStream inputStream = new ByteArrayInputStream(bytes);
                XWPFDocument document = new XWPFDocument(inputStream);
                XWPFWordExtractor extractor = new XWPFWordExtractor(document)
        ) {
            return extractor.getText().strip();
        }
    }

    private String extractDoc(byte[] bytes) throws IOException {
        try (
                InputStream inputStream = new ByteArrayInputStream(bytes);
                HWPFDocument document = new HWPFDocument(inputStream);
                WordExtractor extractor = new WordExtractor(document)
        ) {
            return extractor.getText().strip();
        }
    }

    private String extensionOf(String filename) {
        if (filename == null || filename.isBlank() || !filename.contains(".")) {
            return "";
        }
        return filename.substring(filename.lastIndexOf('.') + 1).trim().toLowerCase(Locale.ROOT);
    }
}

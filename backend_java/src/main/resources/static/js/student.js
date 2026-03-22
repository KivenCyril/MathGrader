const { createApp } = Vue;

const demoData = [
  { id: "Q001", text: "小明买了4袋苹果，每袋6个，一共有多少个苹果？", truth: "24", maxScore: 1 },
  { id: "Q002", text: "一辆车每小时行驶60千米，2.5小时行驶多少千米？", truth: "150", maxScore: 1 }
];

createApp({
  data() {
    return {
      questions: [],
      datasetList: [],
      records: {},
      idx: 0,
      datasetId: "demo",
      levels: [],
      selectedLevel: "",
      loading: false,
      judging: false,
      page: 0,
      pageSize: 50,
      totalQuestions: 0,

      studentAns: "",
      score: 0,
      maxScore: 1,
      note: "",
      showTruth: false,
      useAI: false,
      ocrLoading: false,
      qOcrLoading: false,
      editingQ: false,
      solving: false,
      showHistoryModal: false,
      historyList: [],
      historyLoading: false,
      clearingHistory: false,
      showRubricModal: false,
      rubricText: "",
      rubricFileName: "",
      rubricUploading: false,
      username: "",
      showMobileMenu: false,
      showList: false,
      listCollapsed: false,

      needScore: true,
      enableRecommendation: false,

      lastAIResult: null,
      similarQuestions: [],
      judgingProgressTimer: null,
      judgingJobId: "",
      judgingProgressHeadline: "",
      judgingProgressItems: []
    };
  },
  computed: {
    displayQuestions() {
      return this.questions;
    },
    currentQ() {
      return this.questions[this.idx] || {};
    },
    totalPages() {
      return Math.max(1, Math.ceil(this.totalQuestions / this.pageSize));
    },
    doneCount() {
      return Object.keys(this.records).length;
    },
    totalScore() {
      return Object.values(this.records).reduce((acc, item) => acc + (item.score || 0), 0);
    },
    badgeState() {
      const record = this.records[this.currentQ.id];
      if (record) {
        const aiResult = record.aiResult || null;
        if (aiResult && !aiResult.correct && aiResult.scoring && aiResult.scoring.applied && Number(aiResult.score || 0) > 0) {
          return "partial";
        }
        return record.isCorrect ? "ok" : "bad";
      }
      return "idle";
    },
    analysisView() {
      return this.extractAnalysisView(this.lastAIResult);
    },
    progressView() {
      return this.extractProgressView(this.lastAIResult);
    },
    rubricStatusText() {
      const text = String(this.rubricText || "").trim();
      if (!text) return "当前使用系统默认规则";
      const firstLine = text.split(/\r?\n/).map(line => line.trim()).find(Boolean) || "";
      const preview = firstLine ? firstLine.slice(0, 60) + (firstLine.length > 60 ? "..." : "") : "已输入自定义规则";
      return this.rubricFileName ? (preview + "\n来源: " + this.rubricFileName) : preview;
    },
    activeProgressHeadline() {
      if (this.judging) return this.judgingProgressHeadline || "正在判卷处理中";
      return (this.progressView && this.progressView.headline) || "处理摘要";
    },
    activeProgressItems() {
      if (this.judging) return this.judgingProgressItems;
      return (this.progressView && Array.isArray(this.progressView.items)) ? this.progressView.items : [];
    }
  },
    mounted() {
      this.useAI = localStorage.getItem("useAI") === "true";
      this.listCollapsed = localStorage.getItem("studentListCollapsed") === "true";
      this.init();
  },
  watch: {
    useAI(value) {
      localStorage.setItem("useAI", value);
    },
    listCollapsed(value) {
      localStorage.setItem("studentListCollapsed", value ? "true" : "false");
    }
  },
  methods: {
    renderMath() {
      this.$nextTick(() => {
        if (window.MathJax && window.MathJax.typesetPromise) {
          window.MathJax.typesetPromise().catch(err => console.error("MathJax error:", err));
        }
      });
    },
    async init() {
      try {
        const me = await fetch("/api/agent/me");
        if (me.ok) {
          const user = await me.json();
          this.username = user.username;
        }
      } catch (e) {}

      try {
        const res = await fetch("/api/datasets");
        if (res.ok) this.datasetList = await res.json();
      } catch (e) {}

      this.loadDataset();
    },
    clearRubric() {
      this.rubricText = "";
      this.rubricFileName = "";
    },
    async handleRubricFile(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;

      this.rubricUploading = true;
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/agent/rubric/extract", { method: "POST", body: formData });
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || "评分细则文件解析失败");
        this.rubricText = String(data.text || "").trim();
        this.rubricFileName = String(data.fileName || file.name || "").trim();
        this.showRubricModal = true;
      } catch (err) {
        alert("评分细则上传失败: " + err.message);
      } finally {
        this.rubricUploading = false;
        event.target.value = "";
      }
    },
    async onDatasetChange() {
      this.levels = [];
      this.selectedLevel = "";
      this.page = 0;
      if (this.datasetId !== "demo") {
        try {
          const res = await fetch(`/api/levels?id=${this.datasetId}`);
          if (res.ok) this.levels = await res.json();
        } catch (e) {}
      }
      this.loadDataset();
    },
    addCustomQuestion() {
      const newId = `Q${String(Date.now()).slice(-4)}`;
      const newQuestion = {
        id: newId,
        text: "",
        truth: "",
        maxScore: 1,
        isCustom: true
      };

      this.questions.unshift(newQuestion);
      this.totalQuestions = this.questions.length;
      this.page = 0;
      this.idx = 0;
      this.records = {};
      this.select(0);
      this.editingQ = true;
      this.showTruth = true;
    },
    async solveQuestion() {
      if (!this.currentQ.text) return;
      this.solving = true;
      try {
        const res = await fetch("/api/agent/solve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            questionText: this.currentQ.text,
            enableTools: true,
            mode: "loop",
            maxRounds: 2,
            useLangChain: false
          })
        });
        const data = await res.json();
        if (data.answer) {
          this.currentQ.truth = data.answer;
        } else if (data.error) {
          alert("AI Solve Error: " + data.error);
        }
      } catch (e) {
        alert("AI Solve Failed: " + e.message);
      } finally {
        this.solving = false;
      }
    },
    async handleQuestionOCR(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;

      this.qOcrLoading = true;
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/agent/ocr", { method: "POST", body: formData });
        if (!res.ok) throw new Error("OCR Failed");
        const data = await res.json();
        if (data.text) {
          this.currentQ.text = this.currentQ.text ? `${this.currentQ.text}\n${data.text}` : data.text;
        }
      } catch (err) {
        alert("题目识别失败: " + err.message);
      } finally {
        this.qOcrLoading = false;
        event.target.value = "";
      }
    },
    async loadDataset(options = {}) {
      const {
        targetPage = 0,
        selectedIndex = 0,
        preserveRecords = false
      } = options;

      if (this.datasetId === "demo") {
        this.questions = [...demoData];
        this.totalQuestions = this.questions.length;
        this.page = 0;
        this.idx = Math.min(selectedIndex, Math.max(0, this.questions.length - 1));
      } else {
        this.loading = true;
        try {
          let url = `/api/load?id=${this.datasetId}`;
          if (this.selectedLevel) url += `&level=${encodeURIComponent(this.selectedLevel)}`;
          url += `&page=${targetPage}&pageSize=${this.pageSize}`;

          const res = await fetch(url);
          const payload = await res.json();
          this.questions = Array.isArray(payload.items) ? payload.items : [];
          this.totalQuestions = Number(payload.total || 0);
          this.page = Number.isInteger(payload.page) ? payload.page : targetPage;
          this.idx = Math.min(selectedIndex, Math.max(0, this.questions.length - 1));
        } catch (e) {
          alert("Load failed");
        } finally {
          this.loading = false;
        }
      }

      if (!preserveRecords) this.records = {};
      if (!this.questions.length) {
        this.idx = 0;
        this.clear();
        return;
      }
      this.select(this.idx);
    },
    select(index) {
      if (!this.questions.length) return;
      this.stopJudgingProgress();
      this.judging = false;
      this.idx = Math.max(0, Math.min(index, this.questions.length - 1));

      const question = this.questions[this.idx];
      if (question.isCustom) {
        this.editingQ = true;
        this.showTruth = true;
      } else {
        this.editingQ = false;
        this.showTruth = false;
      }

      const record = this.records[question.id];
      if (record) {
        this.studentAns = record.studentAns;
        this.score = record.score;
        this.maxScore = record.maxScore;
        this.note = record.note;
        this.lastAIResult = record.aiResult || null;
        this.similarQuestions = Array.isArray(record.similarQuestions) ? record.similarQuestions : [];
      } else {
        this.clear();
        this.maxScore = question.maxScore || 1;
      }
      this.renderMath();
    },
    async prev() {
      if (!this.questions.length) return;
      if (this.idx > 0) {
        this.select(this.idx - 1);
        return;
      }
      if (this.datasetId !== "demo" && this.page > 0) {
        await this.loadDataset({ targetPage: this.page - 1, selectedIndex: this.pageSize - 1, preserveRecords: true });
        return;
      }
      if (this.datasetId === "demo") this.select((this.idx - 1 + this.questions.length) % this.questions.length);
    },
    async next() {
      if (!this.questions.length) return;
      if (this.idx < this.questions.length - 1) {
        this.select(this.idx + 1);
        return;
      }
      const hasMorePages = this.datasetId !== "demo" && (this.page + 1) < this.totalPages;
      if (hasMorePages) {
        await this.loadDataset({ targetPage: this.page + 1, selectedIndex: 0, preserveRecords: true });
        return;
      }
      if (this.datasetId === "demo") this.select((this.idx + 1) % this.questions.length);
    },
    async goToPage(targetPage) {
      if (this.datasetId === "demo") {
        this.page = Math.max(0, Math.min(targetPage, this.totalPages - 1));
        this.select(0);
        return;
      }
      if (targetPage < 0 || targetPage >= this.totalPages || targetPage === this.page) return;
      await this.loadDataset({ targetPage, selectedIndex: 0, preserveRecords: true });
    },
    clear() {
      this.studentAns = "";
      this.score = 0;
      this.note = "";
      this.lastAIResult = null;
      this.similarQuestions = [];
      this.stopJudgingProgress();
      this.judging = false;
    },
    resetRecord() {
      delete this.records[this.currentQ.id];
      this.select(this.idx);
    },
    save() {
      if (!this.questions.length) return;
      const isCorrect = this.lastAIResult && typeof this.lastAIResult.correct === "boolean"
        ? this.lastAIResult.correct
        : (this.score > 0 && this.score >= this.maxScore * 0.6);
      this.records[this.currentQ.id] = {
        studentAns: this.studentAns,
        score: this.score,
        maxScore: this.maxScore,
        note: this.note,
        isCorrect,
        aiResult: this.lastAIResult,
        similarQuestions: this.similarQuestions
      };
    },
    escapeHtml(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    },
    renderMathText(value) {
      const escaped = this.escapeHtml(value);
      const withFraction = escaped.replace(/(\d+)\s*\/\s*(\d+)/g, (_, numerator, denominator) => {
        return `<span class="frac"><span class="num">${numerator}</span><span class="den">${denominator}</span></span>`;
      });
      return withFraction.replace(/\n/g, "<br>");
    },
    pickFirstText(...values) {
      for (const value of values) {
        let text = "";
        if (Array.isArray(value)) {
          text = value.map(item => String(item ?? "").trim()).filter(Boolean).join("\n");
        } else if (value && typeof value === "object") {
          continue;
        } else {
          text = String(value ?? "").trim();
        }
        if (text) return text;
      }
      return "";
    },
    extractAnalysisView(result) {
      if (!result || typeof result !== "object") return null;

      const details = result.details && typeof result.details === "object" ? result.details : {};
      const supervisor = details.supervisor_output && typeof details.supervisor_output === "object" ? details.supervisor_output : {};
      const solver = details.solver_output && typeof details.solver_output === "object" ? details.solver_output : {};
      const analysis = supervisor.analysis && typeof supervisor.analysis === "object" ? supervisor.analysis : {};
      const reason = this.pickFirstText(supervisor.reason, result.reason);
      const basis = this.pickFirstText(analysis.basis, analysis.judgement_basis);
      const errorPoint = this.pickFirstText(analysis.error_point, analysis.mistake_point);
      const correctSolution = this.pickFirstText(analysis.correct_solution, analysis.fix);
      const suggestion = this.pickFirstText(analysis.suggestion);
      const keySteps = this.pickFirstText(solver.key_steps);
      const referenceAnswer = this.pickFirstText(solver.reference_answer);

      if (!reason && !basis && !errorPoint && !correctSolution && !suggestion && !keySteps && !referenceAnswer) {
        return null;
      }

      return {
        verdict: result.correct ? "正确" : ((result.scoring && result.scoring.applied && Number(result.score || 0) > 0) ? "部分正确" : "错误"),
        reason,
        basis,
        errorPoint,
        correctSolution,
        suggestion,
        keySteps,
        referenceAnswer
      };
    },
    extractProgressView(result) {
      if (!result || typeof result !== "object") return null;
      const details = result.details && typeof result.details === "object" ? result.details : {};
      const summary = details.progress_summary && typeof details.progress_summary === "object" ? details.progress_summary : null;
      if (!summary || !Array.isArray(summary.items) || summary.items.length === 0) return null;
      return {
        headline: String(summary.headline || "处理摘要"),
        items: this.formatProgressItems(summary.items, false)
      };
    },
    normalizeProgressStatus(status, whileJudging = false) {
      const normalized = String(status || (whileJudging ? "pending" : "done")).trim().toLowerCase();
      if (normalized === "completed") return "done";
      if (normalized === "running") return "active";
      return normalized || (whileJudging ? "pending" : "done");
    },
    inferStageProgress(item, whileJudging = false) {
      const stage = String(item && item.stage || "");
      const status = this.normalizeProgressStatus(item && item.status, whileJudging);
      const explicit = Number(item && item.progress);
      if (Number.isFinite(explicit)) {
        if (status === "done" || status === "failed") return 100;
        return Math.max(0, Math.min(100, explicit));
      }
      if (status === "done" || status === "failed") return 100;
      if (status !== "active") return null;

      const stageDefaults = {
        request_received: 100,
        mcp_rubric_parse: 10,
        answer_equivalence: 20,
        rule_fast_path: 100,
        grade_solver: 40,
        grade_solver_skipped: 45,
        grade_supervisor: 75,
        recommendation_retrieval: 90,
        mcp_scoring_analysis: 95,
        score_mapping: 98
      };
      return Object.prototype.hasOwnProperty.call(stageDefaults, stage) ? stageDefaults[stage] : 15;
    },
    formatProgressItems(items, whileJudging = false) {
      if (!Array.isArray(items)) return [];
      const hiddenStages = new Set(["answer_equivalence", "grade_solver_skipped"]);
      return items
        .filter(item => item && !hiddenStages.has(String(item.stage || "")))
        .map(item => {
          const stage = String(item.stage || "");
          const notes = Array.isArray(item.notes) ? item.notes.map(note => String(note || "").trim()).filter(Boolean) : [];
          const compactStages = new Set(["mcp_scoring_analysis", "score_mapping"]);
          return {
            stage,
            label: String(item.label || "处理阶段"),
            detail: String(item.detail || ""),
            status: this.normalizeProgressStatus(item.status, whileJudging),
            notes: compactStages.has(stage) ? notes.slice(0, 1) : notes.slice(0, 2),
            progress: this.inferStageProgress(item, whileJudging)
          };
        });
    },
    normalizeProgressItems(items) {
      return this.formatProgressItems(items, true);
    },
    startJudgingProgress(snapshot) {
      this.stopJudgingProgress();
      this.judgingJobId = String(snapshot && snapshot.jobId || "");
      this.judgingProgressHeadline = String(snapshot && snapshot.headline || "正在判卷处理中");
      this.judgingProgressItems = this.normalizeProgressItems(snapshot && snapshot.items);
      this.judgingProgressTimer = window.setInterval(() => this.pollJudgingProgress(), 800);
    },
    applyJudgingProgress(snapshot) {
      if (!snapshot || typeof snapshot !== "object") return;
      this.judgingProgressHeadline = String(snapshot.headline || this.judgingProgressHeadline || "正在判卷处理中");
      this.judgingProgressItems = this.normalizeProgressItems(snapshot.items);
    },
    handleJudgingResult(result) {
      this.lastAIResult = result;
      this.similarQuestions = Array.isArray(result.similarQuestions) ? result.similarQuestions : [];
      this.score = (result.scoring && result.scoring.applied === false) ? 0 : result.score;
      this.note = this.formatAnalysisNote(result);
      this.save();
    },
    async pollJudgingProgress() {
      if (!this.judgingJobId) return;
      try {
        const res = await fetch(`/api/agent/grade/progress/${encodeURIComponent(this.judgingJobId)}`);
        const payload = await res.json();
        if (!res.ok) throw new Error(payload.error || "获取判卷进度失败");
        this.applyJudgingProgress(payload);

        const status = String(payload.status || "").toLowerCase();
        if (status === "completed") {
          if (payload.result) this.handleJudgingResult(payload.result);
          this.stopJudgingProgress();
          this.judging = false;
          return;
        }
        if (status === "failed") {
          throw new Error(payload.error || "判卷失败");
        }
      } catch (e) {
        this.stopJudgingProgress();
        this.judging = false;
        alert("AI Error: " + e.message);
      }
    },
    stopJudgingProgress() {
      if (this.judgingProgressTimer) {
        window.clearInterval(this.judgingProgressTimer);
        this.judgingProgressTimer = null;
      }
      this.judgingJobId = "";
      this.judgingProgressHeadline = "";
      this.judgingProgressItems = [];
    },
    formatAnalysisNote(result) {
      const view = this.extractAnalysisView(result);
      if (!view) {
        const lines = [];
        if (result && result.reason) lines.push(result.reason);
        if (result && result.scoring && result.scoring.applied === false) lines.push("本次未计算得分。");
        if (result && result.methodUsed) lines.push(`方法：${result.methodUsed}`);
        lines.push("(AI)");
        return lines.join("\n");
      }

      const lines = [`判定：${view.verdict}`];
      if (view.reason) lines.push(`结论：${view.reason}`);
      if (view.basis) lines.push(`判定依据：${view.basis}`);
      if (view.errorPoint) lines.push(`关键错因：${view.errorPoint}`);
      if (view.correctSolution) lines.push(`正确做法：${view.correctSolution}`);
      if (view.keySteps) lines.push(`参考步骤：\n${view.keySteps}`);
      if (view.referenceAnswer) lines.push(`参考答案：${view.referenceAnswer}`);
      if (view.suggestion) lines.push(`改进建议：${view.suggestion}`);
      if (result && result.methodUsed) lines.push(`方法：${result.methodUsed}`);
      lines.push("(AI)");
      return lines.join("\n\n");
    },
    async judge() {
      if (!this.studentAns.trim()) return;
      if (this.useAI) {
        this.judging = true;
        try {
          const res = await fetch("/api/agent/grade/submit", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              questionText: this.currentQ.text,
              standardAnswer: this.currentQ.truth,
              studentAnswer: this.studentAns,
              maxScore: String(this.maxScore),
              mode: "single",
              datasetId: this.datasetId === "demo" ? null : this.datasetId,
              level: this.selectedLevel || null,
              questionId: this.currentQ.id,
              recommendationCount: 3,
              retrievalTopK: 5,
              enableRecommendation: this.enableRecommendation,
              enableTools: true,
              needScore: this.needScore,
              scoringMode: "auto",
              rubricText: this.rubricText.trim() || null
            })
          });
          const accepted = await res.json();
          if (!res.ok) throw new Error(accepted.error || "提交判卷任务失败");
          this.startJudgingProgress(accepted);
          await this.pollJudgingProgress();
        } catch (e) {
          this.stopJudgingProgress();
          this.judging = false;
          alert("AI Error: " + e.message);
        }
      } else {
        const normalize = value => String(value).trim().replace(/\s+/g, "");
        const correct = normalize(this.studentAns) === normalize(this.currentQ.truth);
        this.score = correct ? this.maxScore : 0;
        this.lastAIResult = null;
        this.similarQuestions = [];
        this.save();
      }
    },
    jumpToSimilarQuestion(item) {
      if (!item || !item.questionId) return;
      const targetIndex = this.questions.findIndex(question => String(question.id) === String(item.questionId));
      if (targetIndex >= 0) {
        this.select(targetIndex);
        this.showList = false;
      }
    },
    async handleOCR(event) {
      const file = event.target.files && event.target.files[0];
      if (!file) return;

      this.ocrLoading = true;
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/agent/ocr", { method: "POST", body: formData });
        if (!res.ok) throw new Error("OCR Failed");
        const data = await res.json();
        if (data.text) {
          this.studentAns = this.studentAns ? `${this.studentAns}\n${data.text}` : data.text;
        }
      } catch (err) {
        alert("识别失败: " + err.message);
      } finally {
        this.ocrLoading = false;
        event.target.value = "";
      }
    },
    exportData() {
      const blob = new Blob([JSON.stringify(this.records, null, 2)], { type: "application/json" });
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = "result.json";
      anchor.click();
    },
    async openHistory() {
      this.showHistoryModal = true;
      this.historyLoading = true;
      this.historyList = [];
      try {
        const res = await fetch("/api/agent/history");
        if (res.ok) this.historyList = await res.json();
      } catch (e) {
        console.error("Fetch history failed", e);
      } finally {
        this.historyLoading = false;
      }
    },
    async clearHistory() {
      if (this.clearingHistory || this.historyLoading || this.historyList.length === 0) return;
      const confirmed = window.confirm("确定要清空历史记录吗？该操作不可恢复。");
      if (!confirmed) return;

      this.clearingHistory = true;
      try {
        const res = await fetch("/api/agent/history", { method: "DELETE" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || data.ok === false) {
          throw new Error(data.message || "清空失败");
        }
        const deleted = Number(data.deleted || 0);
        this.historyList = [];
        alert(`已清空 ${deleted} 条历史记录。`);
      } catch (e) {
        alert("清空历史失败: " + e.message);
      } finally {
        this.clearingHistory = false;
      }
    },
    async logout() {
      const form = document.createElement("form");
      form.method = "POST";
      form.action = "/api/auth/logout";
      document.body.appendChild(form);
      form.submit();
    }
  }
}).mount("#app");

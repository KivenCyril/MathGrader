const { createApp } = Vue;
const demoData = [
  { id:"Q001", text:"小明买了4袋苹果，每袋6个，一共有多少个苹果？", truth:"24", maxScore:1 },
  { id:"Q002", text:"一辆车每小时行驶60千米，2.5小时行驶多少千米？", truth:"150", maxScore:1 }
];

createApp({
  data() {
    return {
      questions: [],
      datasetList: [],
      records: {},
      idx: 0,
      datasetId: 'demo',
      levels: [],
      selectedLevel: '',
      loading: false,
      judging: false,
      page: 0,
      pageSize: 50,
      totalQuestions: 0,

      // Current Edit State
      studentAns: '',
      score: 0,
      maxScore: 1,
      note: '',
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
      username: '',
      showMobileMenu: false,
      showList: false,
      listCollapsed: false,

      // Configurable grading methods from backend.
      gradingMethods: [],
      selectedGradingMethod: 'small_fast',

      // Latest AI result extras
      lastAIResult: null,
      similarQuestions: [],
      judgingProgressTimer: null,
      judgingProgressStartedAt: 0,
      judgingProgressItems: []
    }
  },
  computed: {
    displayQuestions() {
      return this.questions;
    },
    currentQ() { return this.questions[this.idx] || {} },
    totalPages() {
      return Math.max(1, Math.ceil(this.totalQuestions / this.pageSize));
    },
    doneCount() { return Object.keys(this.records).length },
    totalScore() { return Object.values(this.records).reduce((a,b)=>a+(b.score||0), 0) },
    badgeState() {
      const r = this.records[this.currentQ.id];
      if(r) return r.isCorrect ? 'ok' : 'bad';
      return 'idle';
    },
    analysisView() {
      return this.extractAnalysisView(this.lastAIResult);
    },
    progressView() {
      return this.extractProgressView(this.lastAIResult);
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
    useAI(v) { localStorage.setItem("useAI", v); },
    listCollapsed(v) { localStorage.setItem("studentListCollapsed", v ? "true" : "false"); }
  },
  methods: {
    // Use Vue's nextTick to ensure DOM is updated before MathJax rendering
    renderMath() {
      this.$nextTick(() => {
        if (window.MathJax && window.MathJax.typesetPromise) {
          window.MathJax.typesetPromise().catch(err => console.error('MathJax error:', err));
        }
      });
    },
    async init() {
      await this.loadGradingMethods();

      try {
        const me = await fetch('/api/agent/me');
        if(me.ok) {
          const u = await me.json();
          this.username = u.username;
        }
      } catch(e){}

      try {
        const res = await fetch('/api/datasets');
        if(res.ok) this.datasetList = await res.json();
      } catch(e){}
      this.loadDataset();
    },
    async loadGradingMethods() {
      try {
        const res = await fetch('/api/agent/grading-methods');
        if (!res.ok) throw new Error('failed to load grading methods');
        const methods = await res.json();
        if (Array.isArray(methods) && methods.length) {
          this.gradingMethods = methods;
          const defaultMethod = methods.find(m => m.isDefault) || methods[0];
          this.selectedGradingMethod = defaultMethod.id;
          return;
        }
      } catch (e) {
        console.warn('load grading methods failed', e);
      }

      this.gradingMethods = [
        { id: 'small_fast', kind: 'small_fast', label: 'Small Fast (2 Small Datasets)', isDefault: true },
        { id: 'rag_ape', kind: 'rag_ape', label: 'RAG (APE)', isDefault: false }
      ];
      this.selectedGradingMethod = 'small_fast';
    },
    async onDatasetChange() {
      this.levels = [];
      this.selectedLevel = '';
      this.page = 0;
      if(this.datasetId !== 'demo') {
        try {
          const res = await fetch(`/api/levels?id=${this.datasetId}`);
          if(res.ok) this.levels = await res.json();
        } catch(e) {}
      }
      // Auto load or wait for user? Let's auto load to keep behavior consistent
      this.loadDataset();
    },
    addCustomQuestion() {
      const newId = `Q${String(Date.now()).slice(-4)}`;
      const newQ = {
        id: newId,
        text: "",
        truth: "",
        maxScore: 1,
        isCustom: true
      };

      this.questions.unshift(newQ);
      this.totalQuestions = this.questions.length;
      this.page = 0;
      this.idx = 0;
      this.records = {};
      this.select(0);
      this.editingQ = true;
      this.showTruth = true;
    },
    async solveQuestion() {
      if(!this.currentQ.text) return;
      this.solving = true;
      try {
        const res = await fetch("/api/agent/solve", {
          method: "POST", headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            questionText: this.currentQ.text,
            enableTools: true,
            mode: "loop",
            maxRounds: 2,
            useLangChain: false
          })
        });
        const data = await res.json();
        if(data.answer) {
          this.currentQ.truth = data.answer;
        } else if(data.error) {
          alert("AI Solve Error: " + data.error);
        }
      } catch(e) {
        alert("AI Solve Failed: " + e.message);
      } finally {
        this.solving = false;
      }
    },
    async handleQuestionOCR(e) {
      const file = e.target.files?.[0];
      if(!file) return;

      this.qOcrLoading = true;
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/agent/ocr", { method: "POST", body: formData });
        if(!res.ok) throw new Error("OCR Failed");
        const data = await res.json();
        if(data.text) {
          if(!this.currentQ.text) this.currentQ.text = data.text;
          else this.currentQ.text += "\n" + data.text;
        }
      } catch(err) {
        alert("题目识别失败: " + err.message);
      } finally {
        this.qOcrLoading = false;
        e.target.value = "";
      }
    },
    async loadDataset(options = {}) {
      const {
        targetPage = 0,
        selectedIndex = 0,
        preserveRecords = false
      } = options;

      if(this.datasetId === 'demo') {
        this.questions = [...demoData];
        this.totalQuestions = this.questions.length;
        this.page = 0;
        this.idx = Math.min(selectedIndex, Math.max(0, this.questions.length - 1));
      } else {
        this.loading = true;
        try {
          let url = `/api/load?id=${this.datasetId}`;
          if(this.selectedLevel) url += `&level=${encodeURIComponent(this.selectedLevel)}`;
          url += `&page=${targetPage}&pageSize=${this.pageSize}`;

          const res = await fetch(url);
          const payload = await res.json();
          this.questions = Array.isArray(payload.items) ? payload.items : [];
          this.totalQuestions = Number(payload.total || 0);
          this.page = Number.isInteger(payload.page) ? payload.page : targetPage;
          this.idx = Math.min(selectedIndex, Math.max(0, this.questions.length - 1));
        } catch(e){ alert("Load failed"); }
        finally { this.loading = false; }
      }
      if (!preserveRecords) this.records = {};
      if (!this.questions.length) {
        this.idx = 0;
        this.clear();
        return;
      }
      this.select(this.idx);
    },
    select(i) {
      if(!this.questions.length) return;
      this.stopJudgingProgress();
      this.idx = Math.max(0, Math.min(i, this.questions.length - 1));

      const q = this.questions[this.idx];
      if(q.isCustom) {
        this.editingQ = true;
        this.showTruth = true;
      } else {
        this.editingQ = false;
        this.showTruth = false;
      }

      const r = this.records[q.id];
      if(r) {
        this.studentAns = r.studentAns;
        this.score = r.score;
        this.maxScore = r.maxScore;
        this.note = r.note;
        this.lastAIResult = r.aiResult || null;
        this.similarQuestions = Array.isArray(r.similarQuestions) ? r.similarQuestions : [];
      } else {
        this.clear();
        this.maxScore = q.maxScore || 1;
      }
      this.renderMath();
    },
    async prev() {
      if(!this.questions.length) return;
      if (this.idx > 0) {
        this.select(this.idx - 1);
        return;
      }
      if (this.datasetId !== 'demo' && this.page > 0) {
        await this.loadDataset({ targetPage: this.page - 1, selectedIndex: this.pageSize - 1, preserveRecords: true });
        return;
      }
      if (this.datasetId === 'demo') {
        this.select((this.idx - 1 + this.questions.length) % this.questions.length);
      }
    },
    async next() {
      if(!this.questions.length) return;
      if (this.idx < this.questions.length - 1) {
        this.select(this.idx + 1);
        return;
      }
      const hasMorePages = this.datasetId !== 'demo' && (this.page + 1) < this.totalPages;
      if (hasMorePages) {
        await this.loadDataset({ targetPage: this.page + 1, selectedIndex: 0, preserveRecords: true });
        return;
      }
      if (this.datasetId === 'demo') {
        this.select((this.idx + 1) % this.questions.length);
      }
    },
    async goToPage(targetPage) {
      if (this.datasetId === 'demo') {
        this.page = Math.max(0, Math.min(targetPage, this.totalPages - 1));
        this.select(0);
        return;
      }
      if (targetPage < 0 || targetPage >= this.totalPages || targetPage === this.page) return;
      await this.loadDataset({ targetPage, selectedIndex: 0, preserveRecords: true });
    },
    clear() {
      this.studentAns = '';
      this.score = 0;
      this.note = '';
      this.lastAIResult = null;
      this.similarQuestions = [];
      this.stopJudgingProgress();
      this.judgingProgressItems = [];
    },
    resetRecord() { delete this.records[this.currentQ.id]; this.select(this.idx); },

    save() {
      if(!this.questions.length) return;
      const isCorrect = this.score > 0 && this.score >= this.maxScore * 0.6;
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
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    },
    renderMathText(value) {
      const escaped = this.escapeHtml(value);
      const withFraction = escaped.replace(/(\d+)\s*\/\s*(\d+)/g, (_, numerator, denominator) => {
        return `<span class="frac"><span class="num">${numerator}</span><span class="den">${denominator}</span></span>`;
      });
      return withFraction.replace(/\n/g, '<br>');
    },
    pickFirstText(...values) {
      for (const value of values) {
        let text = '';
        if (Array.isArray(value)) {
          text = value.map(item => String(item ?? '').trim()).filter(Boolean).join('\n');
        } else if (value && typeof value === 'object') {
          continue;
        } else {
          text = String(value ?? '').trim();
        }
        if (text) return text;
      }
      return '';
    },
    extractAnalysisView(result) {
      if (!result || typeof result !== 'object') return null;

      const details = (result.details && typeof result.details === 'object') ? result.details : {};
      const supervisor = (details.supervisor_output && typeof details.supervisor_output === 'object') ? details.supervisor_output : {};
      const solver = (details.solver_output && typeof details.solver_output === 'object') ? details.solver_output : {};
      const analysis = (supervisor.analysis && typeof supervisor.analysis === 'object') ? supervisor.analysis : {};

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
        verdict: result.correct ? '正确' : '错误',
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
      if (!result || typeof result !== 'object') return null;
      const details = (result.details && typeof result.details === 'object') ? result.details : {};
      const summary = (details.progress_summary && typeof details.progress_summary === 'object') ? details.progress_summary : null;
      if (!summary || !Array.isArray(summary.items) || summary.items.length === 0) return null;
      return {
        headline: String(summary.headline || '处理摘要'),
        items: summary.items.map(item => ({
          stage: String(item.stage || ''),
          label: String(item.label || '处理中'),
          detail: String(item.detail || ''),
          status: String(item.status || 'done')
        }))
      };
    },
    startJudgingProgress() {
      this.stopJudgingProgress();
      this.judgingProgressStartedAt = Date.now();
      this.judgingProgressItems = [
        { stage: 'request_received', label: '已接收题目', detail: '正在提交判卷请求', status: 'done' },
        { stage: 'answer_equivalence', label: '答案快速比对', detail: '正在检查学生答案与标准答案是否可直接判定', status: 'active' },
        { stage: 'grade_supervisor', label: '生成判卷结论', detail: '正在结合题目、标答和学生答案生成判卷结果', status: 'pending' },
        { stage: 'recommendation_retrieval', label: '检索相似题', detail: '如判错，将补充相似题推荐', status: 'pending' }
      ];
      this.judgingProgressTimer = window.setInterval(() => this.updateJudgingProgress(), 1200);
    },
    updateJudgingProgress() {
      const elapsedMs = Date.now() - this.judgingProgressStartedAt;
      const items = this.judgingProgressItems.map(item => ({ ...item }));
      if (elapsedMs >= 1500 && items[1]) {
        items[1].status = 'done';
        if (items[2]) items[2].status = 'active';
      }
      if (elapsedMs >= 5500 && items[2]) {
        items[2].status = 'done';
        if (items[3]) items[3].status = 'active';
      }
      this.judgingProgressItems = items;
    },
    stopJudgingProgress() {
      if (this.judgingProgressTimer) {
        window.clearInterval(this.judgingProgressTimer);
        this.judgingProgressTimer = null;
      }
      this.judgingProgressStartedAt = 0;
    },
    formatAnalysisNote(result) {
      const view = this.extractAnalysisView(result);
      if (!view) {
        const lines = [];
        if (result && result.reason) lines.push(result.reason);
        if (result && result.methodUsed) lines.push(`方法：${result.methodUsed}`);
        lines.push('(AI)');
        return lines.join('\n');
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

      lines.push('(AI)');
      return lines.join('\n\n');
    },

    async judge() {
      if(!this.studentAns.trim()) return;
      if(this.useAI) {
        this.judging = true;
        this.startJudgingProgress();
        try {
          const res = await fetch("/api/agent/grade", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              questionText: this.currentQ.text,
              standardAnswer: this.currentQ.truth,
              studentAnswer: this.studentAns,
              maxScore: String(this.maxScore),
              mode: 'single',
              gradingMethod: this.selectedGradingMethod,
              datasetId: this.datasetId === 'demo' ? null : this.datasetId,
              level: this.selectedLevel || null,
              questionId: this.currentQ.id,
              recommendationCount: 3,
              retrievalTopK: 5,
              enableTools: true
            })
          });
          const ret = await res.json();

          this.lastAIResult = ret;
          this.similarQuestions = Array.isArray(ret.similarQuestions) ? ret.similarQuestions : [];
          this.score = ret.score;
          this.note = this.formatAnalysisNote(ret);

          this.save();
        } catch(e) {
          alert("AI Error: " + e.message);
        } finally {
          this.stopJudgingProgress();
          this.judging = false;
        }
      } else {
        const norm = s => String(s).trim().replace(/\s+/g,"");
        const ok = norm(this.studentAns) == norm(this.currentQ.truth);
        this.score = ok ? this.maxScore : 0;
        this.lastAIResult = null;
        this.similarQuestions = [];
        this.save();
      }
    },

    jumpToSimilarQuestion(item) {
      if (!item || !item.questionId) return;
      const targetIndex = this.questions.findIndex(q => String(q.id) === String(item.questionId));
      if (targetIndex >= 0) {
        this.select(targetIndex);
        this.showList = false;
      }
    },

    async handleOCR(e) {
      const file = e.target.files?.[0];
      if(!file) return;

      this.ocrLoading = true;
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch("/api/agent/ocr", {
          method: "POST",
          body: formData
        });
        if(!res.ok) throw new Error("OCR Failed");
        const data = await res.json();
        if(data.text) {
          if(!this.studentAns) this.studentAns = data.text;
          else this.studentAns += "\n" + data.text;
        }
      } catch(err) {
        alert("识别失败: " + err.message);
      } finally {
        this.ocrLoading = false;
        e.target.value = "";
      }
    },

    exportData() {
      const blob = new Blob([JSON.stringify(this.records, null, 2)], {type:"application/json"});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "result.json";
      a.click();
    },
    async openHistory() {
      this.showHistoryModal = true;
      this.historyLoading = true;
      this.historyList = [];
      try {
        const res = await fetch("/api/agent/history");
        if(res.ok) {
          this.historyList = await res.json();
        }
      } catch(e) {
        console.error("Fetch history failed", e);
      } finally {
        this.historyLoading = false;
      }
    },
    async clearHistory() {
      if (this.clearingHistory || this.historyLoading || this.historyList.length === 0) return;
      const ok = window.confirm("确定要清空历史记录吗？该操作不可恢复。");
      if (!ok) return;

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
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/api/auth/logout';
      document.body.appendChild(form);
      form.submit();
    }
  }
}).mount('#app');



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
      username: '',
      showMobileMenu: false,
      showList: false,

      // Configurable grading methods from backend.
      gradingMethods: [],
      selectedGradingMethod: 'small_fast',
      enableMethodCompare: false,
      compareMethod: '',

      // Latest AI result extras
      lastAIResult: null,
      similarQuestions: []
    }
  },
  computed: {
    displayQuestions() {
      const start = this.page * this.pageSize;
      return this.questions.slice(start, start + this.pageSize);
    },
    currentQ() { return this.questions[this.idx] || {} },
    doneCount() { return Object.keys(this.records).length },
    totalScore() { return Object.values(this.records).reduce((a,b)=>a+(b.score||0), 0) },
    badgeState() {
      const r = this.records[this.currentQ.id];
      if(r) return r.isCorrect ? 'ok' : 'bad';
      return 'idle';
    },
    compareMethodOptions() {
      return this.gradingMethods.filter(m => m.id !== this.selectedGradingMethod);
    },
    comparisonEntries() {
      if (!this.lastAIResult || !this.lastAIResult.comparison) return [];
      return Object.entries(this.lastAIResult.comparison);
    }
  },
  mounted() {
    this.useAI = localStorage.getItem("useAI") === "true";
    this.init();
  },
  watch: {
    useAI(v) { localStorage.setItem("useAI", v); },
    selectedGradingMethod() {
      if (this.compareMethod === this.selectedGradingMethod) {
        const fallback = this.compareMethodOptions[0];
        this.compareMethod = fallback ? fallback.id : '';
      }
    }
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
          const compareFallback = methods.find(m => m.id !== defaultMethod.id);
          this.compareMethod = compareFallback ? compareFallback.id : '';
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
      this.compareMethod = 'rag_ape';
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
    async loadDataset() {
      if(this.datasetId === 'demo') {
        this.questions = [...demoData];
      } else {
        this.loading = true;
        try {
          let url = `/api/load?id=${this.datasetId}`;
          if(this.selectedLevel) url += `&level=${encodeURIComponent(this.selectedLevel)}`;

          const res = await fetch(url);
          this.questions = await res.json();
        } catch(e){ alert("Load failed"); }
        finally { this.loading = false; }
      }
      this.idx = 0; this.page = 0; this.records = {}; this.select(0);
    },
    select(i) {
      if(!this.questions.length) return;
      this.idx = i;
      const p = Math.floor(i / this.pageSize);
      if(p !== this.page) this.page = p;

      const q = this.questions[i];
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
    prev() { if(this.questions.length) this.select((this.idx - 1 + this.questions.length) % this.questions.length); },
    next() { if(this.questions.length) this.select((this.idx + 1) % this.questions.length); },
    clear() {
      this.studentAns = '';
      this.score = 0;
      this.note = '';
      this.lastAIResult = null;
      this.similarQuestions = [];
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

    buildComparisonSummary(result) {
      if (!result || !result.comparison) return '';
      const parts = [];
      for (const [name, value] of Object.entries(result.comparison)) {
        parts.push(`${name}: score=${value.score}, correct=${value.correct}`);
      }
      return parts.join(' | ');
    },

    async judge() {
      if(!this.studentAns.trim()) return;
      if(this.useAI) {
        this.judging = true;
        try {
          const compareMethods = this.enableMethodCompare && this.compareMethod ? [this.compareMethod] : [];
          const res = await fetch("/api/agent/grade", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              questionText: this.currentQ.text,
              standardAnswer: this.currentQ.truth,
              studentAnswer: this.studentAns,
              maxScore: String(this.maxScore),
              mode: 'single',
              gradingMethod: this.selectedGradingMethod,
              compareMethods,
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

          const lines = [];
          if (ret.reason) lines.push(ret.reason);
          if (ret.methodUsed) lines.push(`method: ${ret.methodUsed}`);
          const comparisonSummary = this.buildComparisonSummary(ret);
          if (comparisonSummary) lines.push(`compare: ${comparisonSummary}`);
          lines.push('(AI)');
          this.note = lines.join('\n');

          this.save();
        } catch(e) {
          alert("AI Error: " + e.message);
        } finally {
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
    async logout() {
      const form = document.createElement('form');
      form.method = 'POST';
      form.action = '/api/auth/logout';
      document.body.appendChild(form);
      form.submit();
    }
  }
}).mount('#app');



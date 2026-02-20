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
      solving: false
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
    }
  },
  mounted() {
    this.useAI = localStorage.getItem("useAI") === "true";
    this.init();
  },
  watch: {
    useAI(v) { localStorage.setItem("useAI", v); }
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
      try {
        const res = await fetch('/api/datasets');
        if(res.ok) this.datasetList = await res.json();
      } catch(e){}
      this.loadDataset();
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
      // Create a new question object
      const newId = `Q${String(Date.now()).slice(-4)}`;
      const newQ = {
        id: newId,
        text: "",
        truth: "",
        maxScore: 1,
        isCustom: true
      };
      
      // Add to beginning of questions list
      this.questions.unshift(newQ);
      
      // Select it and enable edit mode
      this.page = 0;
      this.idx = 0;
      this.records = {}; // Reset records for simplicity or keep? Resetting might be annoying.
      // Better: keep records but clear for this new Q
      this.select(0);
      this.editingQ = true;
      this.showTruth = true; // Show truth field so user can edit it
    },
    async solveQuestion() {
        if(!this.currentQ.text) return;
        this.solving = true;
        try {
            const res = await fetch("/api/agent/solve", {
                method: "POST", headers: {"Content-Type": "application/json"},
                body: JSON.stringify({ questionText: this.currentQ.text })
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
      // Auto jump to page
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
      } else {
        this.clear();
        this.maxScore = q.maxScore || 1;
      }
      this.renderMath(); // Trigger MathJax
    },
    prev() { if(this.questions.length) this.select((this.idx - 1 + this.questions.length) % this.questions.length); },
    next() { if(this.questions.length) this.select((this.idx + 1) % this.questions.length); },
    clear() { this.studentAns = ''; this.score = 0; this.note = ''; },
    resetRecord() { delete this.records[this.currentQ.id]; this.select(this.idx); },
    
    save() {
      if(!this.questions.length) return;
      const isCorrect = this.score > 0 && this.score >= this.maxScore * 0.6;
      this.records[this.currentQ.id] = {
        studentAns: this.studentAns, score: this.score, maxScore: this.maxScore, note: this.note, isCorrect
      };
    },
    
    async judge() {
      if(!this.studentAns.trim()) return;
      if(this.useAI) {
        this.judging = true;
        try {
          const res = await fetch("/api/agent/grade", {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              questionText: this.currentQ.text, standardAnswer: this.currentQ.truth,
              studentAnswer: this.studentAns, maxScore: String(this.maxScore)
            })
          });
          const ret = await res.json();
          this.score = ret.score;
          this.note = (ret.reason || "") + "\n(AI)";
          // Temp save to update badge state immediately visually
          this.save(); 
        } catch(e) { alert("AI Error: "+e.message); }
        finally { this.judging = false; }
      } else {
        // Simple local check
        const norm = s => String(s).trim().replace(/\s+/g,"");
        const ok = norm(this.studentAns) == norm(this.currentQ.truth);
        this.score = ok ? this.maxScore : 0;
        this.save();
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
          // Append or replace? Let's replace if empty, append if not
          if(!this.studentAns) this.studentAns = data.text;
          else this.studentAns += "\n" + data.text;
        }
      } catch(err) {
        alert("识别失败: " + err.message);
      } finally {
        this.ocrLoading = false;
        e.target.value = ""; // reset input
      }
    },
    
    exportData() {
      const blob = new Blob([JSON.stringify(this.records, null, 2)], {type:"application/json"});
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "result.json";
      a.click();
    },
    switchRole() {
      localStorage.removeItem('math_grader_role');
      window.location.href = '/';
    }
  }
}).mount('#app');
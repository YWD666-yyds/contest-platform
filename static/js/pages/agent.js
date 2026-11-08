/** 设计智能体：题目要求 → 引导式设计 → 对话测试与提交任务。 */
import { api } from "../api.js?v=12";
import { h, $, toastOk, toastErr, badge, modal, confirmBox } from "../ui.js?v=12";
import { setNav, rerender } from "../app.js?v=12";

let step = 1;
let agent = null;
let task = null;
let chatEnabled = false;
let windowOpen = true;   // 答题时间（实操考试窗口）：true=设计期，false=体验期（配置锁定，仅供展示与体验）
let history = [];

const FIELD_DEFS = [
  { key: "name", label: "智能体名称", required: true, max: 30, ph: "如：社区垃圾分类小管家",
    hint: "起一个好记的名字，体现它的用途。" },
  { key: "audience", label: "服务对象", required: true, max: 50, ph: "如：社区居民、独居老人、小学生",
    hint: "谁会使用它？想清楚服务对象，才能设计合适的语气和功能。" },
  { key: "scenario", label: "应用场景", required: true, max: 200, ph: "如：社区垃圾投放点，居民不确定垃圾类别时前来询问",
    hint: "它在什么地方、什么情况下被使用？取材于真实生活场景。" },
  { key: "role", label: "角色定位", required: true, max: 500, ph: "如：你是一名耐心的垃圾分类指导员，熟悉本市最新垃圾分类标准…",
    hint: "用一句话描述「它是谁」。这段话会告诉 AI 如何扮演这个角色。" },
  { key: "problem", label: "要解决的便民问题", required: true, max: 500, ph: "如：居民常分不清垃圾类别，投错率高，二次分拣成本大",
    hint: "发现的真实便民问题要具体明确，这是选题的核心。" },
  { key: "skills", label: "功能与技能（选填）", required: false, max: 500, ph: "如：判断垃圾类别并说明原因；提醒投放时间；满溢时提示联系物业",
    hint: "它应该会做什么？功能要与便民问题一一对应。" },
  { key: "knowledge", label: "知识资料（选填）", required: false, max: 2000, ph: "粘贴它需要掌握的资料，如：可回收物：纸类、塑料瓶…",
    hint: "把你知道的规定、流程、说明喂给它，回答会更准确。" },
  { key: "tone", label: "语气风格", required: true, max: 50, ph: "如：亲切耐心、多用 emoji、给老人讲解时放慢语速",
    hint: "面向老人要耐心简单，面向学生可以活泼一些。" },
  { key: "welcome", label: "开场白（选填）", required: false, max: 200, ph: "如：您好！我是垃圾分类小管家，请告诉我您手上的垃圾是什么？",
    hint: "对话开始时它说的第一句话。" },
];

export async function render(app) {
  setNav("");
  clearInterval(window.__examPoll);  // 离开页面时停止上一轮判题轮询
  app.innerHTML = "";
  app.append(h("div", { class: "text-c muted", style: "padding:60px 0" }, "加载中…"));
  const data = await api.get("/api/student/task");
  task = data.task;
  agent = data.agent;
  chatEnabled = data.chat_enabled;
  windowOpen = data.window_open !== false;
  history = data.history || [];
  step = agent ? 3 : 1;

  // OJ 实操考试数据（失败不阻塞页面）
  let examData = null;
  try { examData = await api.get("/api/student/agent-exam"); } catch { /* ignore */ }

  app.innerHTML = "";
  const head = h("div", { class: "spread mb16" },
    h("h2", { style: "margin:0" }, "🤖 设计智能体"),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => { location.hash = "#/me"; } }, "← 返回工作台"));
  const stepsBar = h("div", { class: "steps", id: "agent-steps" });
  const body = h("div", {});
  app.append(head);
  let examBox = null;
  if (examData && examData.exam.enabled) {
    examBox = buildExamCard(examData);
    app.append(examBox);
  }
  app.append(stepsBar, body);

  function startExamPoll() {
    clearInterval(window.__examPoll);
    window.__examPoll = setInterval(async () => {
      try {
        const d = await api.get("/api/student/agent-exam");
        if (!d.result || d.result.status !== "running") {
          clearInterval(window.__examPoll);
          examData = d;
          const fresh = buildExamCard(d);
          examBox.replaceWith(fresh);
          examBox = fresh;
        }
      } catch { /* 轮询失败忽略 */ }
    }, 3000);
  }
  if (examData && examData.result && examData.result.status === "running") startExamPoll();

  function draw() {
    stepsBar.innerHTML = "";
    ["① 阅读题目要求", "② 设计智能体", "③ 对话测试"].forEach((lbl, i) => {
      const n = i + 1;
      const canJump = n <= 2 || (agent && ["saved", "submitted"].includes(agent.status));
      stepsBar.append(h("div", {
        class: `step ${n < step ? "done" : n === step ? "active" : ""}`,
        style: canJump ? "cursor:pointer" : "",
        onclick: () => { if (canJump) { step = n; draw(); } },
      },
        h("div", { class: "dot" }, n < step ? "✓" : String(n)),
        h("div", { class: "lbl" }, lbl)));
    });
    body.innerHTML = "";
    if (step === 1) body.append(stepTask());
    if (step === 2) body.append(stepDesign());
    if (step === 3) body.append(stepChat());
  }

  /* ---- 步骤 1：题目要求 ---- */
  function stepTask() {
    return h("div", { class: "card" },
      h("div", { class: "card-title" }, h("h3", {}, `📋 ${task.title}`)),
      h("div", { class: "task-doc", style: "white-space:pre-wrap;line-height:1.9;font-size:14.5px;color:var(--ink-2)" },
        task.content || "（老师还没有发布题目要求）"),
      h("div", { class: "row mt16", style: "justify-content:flex-end" },
        h("button", { class: "btn btn-lg", onclick: () => { step = 2; draw(); } }, "我已阅读，开始设计 →")),
    );
  }

  /* ---- 步骤 2：引导式设计 ---- */
  function stepDesign() {
    const isSubmitted = agent && agent.status === "submitted";
    const locked = agent && agent.check_status === "ok";
    const readOnly = isSubmitted || locked || !windowOpen;
    const inputs = {};
    const form = h("div", {});
    for (const def of FIELD_DEFS) {
      const isLong = def.max >= 500;
      let input;
      if (isLong) {
        input = h("textarea", { class: "textarea", rows: 3, maxlength: def.max, placeholder: def.ph, disabled: readOnly });
      } else {
        input = h("input", { class: "input", maxlength: def.max, placeholder: def.ph, disabled: readOnly });
      }
      input.value = (agent && agent[def.key]) || "";
      inputs[def.key] = input;
      form.append(h("div", { class: "field" },
        h("label", { class: def.required ? "req" : "" }, def.label),
        input,
        h("p", { class: "hint" }, def.hint)));
    }

    return h("div", { class: "card" },
      readOnly
        ? h("div", { class: "callout warn mb16" },
            locked
              ? "当前智能体任务已检测合格并锁定，处于只读查看模式。"
              : !windowOpen
                ? "⏳ 答题时间已结束，智能体配置已锁定，仅供展示与体验；可在「③ 对话测试」中以体验模式验证效果。"
                : "当前智能体任务已提交，处于只读查看模式。如需修改设计，请先在「③ 对话测试」页面点击「撤回修改」。")
        : h("div", { class: "callout mb16" },
            "按照下面的问题一步步填写，就像给智能体做一张「身份证」。带 * 的为必填；"
            + "填写内容会组成它的系统提示词，决定它如何回答。"),
      form,
      h("div", { class: "row", style: "justify-content:space-between" },
        h("button", { class: "btn btn-ghost", onclick: () => { step = 1; draw(); } }, "← 回看题目要求"),
        readOnly
          ? h("button", { class: "btn", onclick: () => { step = 3; draw(); } }, "前往对话测试 →")
          : h("button", { class: "btn btn-lg", onclick: doSave }, "💾 保存设计")),
    );

    async function doSave() {
      const body = {};
      for (const def of FIELD_DEFS) body[def.key] = inputs[def.key].value.trim();
      try {
        const r = await api.put("/api/student/agent", body);
        agent = { ...(agent || {}), ...r.agent, status: "saved" };
        toastOk("设计已保存！可以开始对话测试了");
        step = 3; draw();
      } catch (e) { toastErr(e.message); }
    }
  }

  /* ---- 步骤 3：对话测试 ---- */
  function stepChat() {
    if (!agent || !["saved", "submitted"].includes(agent.status)) {
      return h("div", { class: "card lock-screen" },
        h("p", { class: "muted" }, "请先完成并保存智能体设计"),
        h("button", { class: "btn mt16", onclick: () => { step = 2; draw(); } }, "去设计"));
    }

    const isSubmitted = agent.status === "submitted";
    const locked = agent.check_status === "ok";
    // 设计期：提交/检测合格后对话只读（保持评审记录干净）；体验期（答题时间结束）：开放体验对话，供老师线下验证
    const chatReadOnly = windowOpen ? (isSubmitted || locked) : false;

    const log = h("div", { class: "chat-log", id: "chat-log" });
    const input = h("input", {
      class: "input", id: "chat-input", maxlength: 500, disabled: chatReadOnly,
      placeholder: !windowOpen
        ? "体验模式：向你的智能体提问，验证它是否符合设计要求"
        : locked
          ? "任务已检测合格并锁定"
          : isSubmitted
            ? "任务已提交，如需继续对话测试请先点击上方「撤回修改」"
            : "用居民的口吻向你的智能体提问，如：剩饭剩菜属于什么垃圾？",
    });
    const sendBtn = h("button", { class: "btn", id: "chat-send", disabled: chatReadOnly, onclick: send }, "发送 ➤");

    if (agent.welcome && !history.length) {
      history = [{ role: "assistant", content: agent.welcome, created_at: "" }];
    }

    // 对话轮数：仅统计获得真实 AI 回复的提问（警告/错误回复不计入，防止 LLM 未配置时"空转"凑轮数）
    const getChatRounds = () => {
      let rounds = 0;
      for (let i = 0; i < history.length; i++) {
        if (history[i].role === "user" && history[i + 1] &&
            history[i + 1].role === "assistant" && !history[i + 1].error) rounds++;
      }
      return rounds;
    };
    const roundsSpan = h("span", { class: "small muted" }, "");
    function updateRoundsText() {
      if (!windowOpen) {
        roundsSpan.textContent = "已截止 · 体验模式（新对话仅供展示验证，不计入评审）" +
          (agent.submitted_at ? ` · 提交于 ${agent.submitted_at.slice(0, 16)}` : "");
        return;
      }
      const r = getChatRounds();
      roundsSpan.textContent = `已完成对话 ${r} 轮（提交至少需 2 轮）` +
        (agent.submitted_at ? ` · 提交于 ${agent.submitted_at.slice(0, 16)}` : "");
    }

    function bubble(role, content, kind = "") {
      if (role === "assistant") {
        return h("div", { class: `chat-row ${kind === "error" ? "chat-err" : ""}` },
          h("div", { class: "chat-bubble ai" }, kind === "error"
            ? [h("div", {}, "⚠️ ", content),
               h("div", { class: "small muted mt8" }, "（该提示已同步展示给老师侧日志；请举手示意老师处理）")]
            : content));
      }
      return h("div", { class: "chat-row me" }, h("div", { class: "chat-bubble user" }, content));
    }

    function renderLog() {
      log.innerHTML = "";
      if (!history.length) {
        log.append(h("div", { class: "text-c muted", style: "padding:30px 10px" },
          "还没有对话。试着扮演一位居民，问它一个真实问题吧！"));
      }
      for (const m of history) {
        log.append(m.error ? bubble("assistant", m.content, "error") : bubble(m.role, m.content));
      }
      log.scrollTop = log.scrollHeight;
      updateRoundsText();
    }

    async function send() {
      if (chatReadOnly) return;
      const text = input.value.trim();
      if (!text) return;
      input.value = "";
      sendBtn.disabled = true;
      history.push({ role: "user", content: text });
      renderLog();
      log.append(h("div", { class: "chat-row", id: "chat-typing" },
        h("div", { class: "chat-bubble ai muted" }, "思考中…")));
      log.scrollTop = log.scrollHeight;
      try {
        const r = await api.post("/api/student/agent/chat", { message: text });
        history.pop(); // 重新以服务端口径渲染
        if (r.ok) {
          history.push({ role: "user", content: text }, { role: "assistant", content: r.reply });
        } else {
          history.push({ role: "user", content: text }, { role: "assistant", content: r.error, error: true });
        }
      } catch (e) {
        history.pop();
        history.push({ role: "user", content: text }, { role: "assistant", content: e.message, error: true });
      } finally {
        sendBtn.disabled = false;
        renderLog();
        input.focus();
      }
    }

    input.addEventListener("keydown", (e) => { if (e.key === "Enter") send(); });

    /* 任务提交状态栏 */
    updateRoundsText();
    const taskBar = h("div", { class: "card mb16" },
      h("div", { class: "spread" },
        h("div", { class: "row" },
          isSubmitted ? badge("任务已提交", "ok") : badge("设计已保存", "info"),
          locked && badge("检测合格 ✓", "ok"),
          agent.check_status === "revise" && badge("需修改", "warn"),
          roundsSpan),
        h("div", { class: "row" },
          agent.check_status === "revise" && agent.check_comment &&
          h("span", { class: "small", style: "color:var(--warn)" }, `老师备注：${agent.check_comment}`),
          windowOpen && isSubmitted && !locked &&
          h("button", { class: "btn btn-ghost btn-sm", onclick: doRetract }, "撤回修改"),
          windowOpen && !isSubmitted && !locked &&
          h("button", { class: "btn btn-ok", onclick: doSubmitTask }, "📤 交任务")),
      ),
      locked && h("p", { class: "small muted", style: "margin:8px 0 0" },
        "任务已检测合格并锁定，不可再修改。如确需调整请联系老师。"),
      !windowOpen && h("p", { class: "small muted", style: "margin:8px 0 0" },
        "⏳ 答题时间已结束：配置已锁定，仅供展示与体验；新对话不计入评审、不会保存。老师可在现场验证后于管理端记录检测结论。"),
    );

    async function doSubmitTask() {
      if (getChatRounds() < 2) {
        toastErr(chatEnabled
          ? "对话测试不足 2 轮，请先用居民的口吻提问至少 2 次"
          : "对话功能尚未开放（老师尚未配置大模型），开放后完成 2 轮真实对话测试即可提交");
        return;
      }
      modal({
        title: "确认交任务？",
        body: h("div", {},
          h("p", {}, "提交后老师将检测你的智能体设计与对话效果。"),
          h("p", { class: "small muted" }, "检测合格前可撤回修改；检测合格后锁定。")),
        actions: (close) => [
          h("button", { class: "btn btn-ghost", onclick: close }, "再检查一下"),
          h("button", { class: "btn btn-ok", onclick: async () => {
            close();
            try { await api.post("/api/student/agent/submit"); toastOk("任务提交成功！"); rerender(); }
            catch (e) { toastErr(e.message); }
          } }, "确认提交"),
        ],
      });
    }

    async function doRetract() {
      confirmBox("撤回后任务回到「已保存」状态，可继续修改后再次提交。确定撤回？", async () => {
        try { await api.post("/api/student/agent/retract"); toastOk("已撤回"); rerender(); }
        catch (e) { toastErr(e.message); }
      });
    }

    renderLog();

    return h("div", {},
      taskBar,
      !windowOpen && h("div", { class: "callout warn mb16" },
        "🎓 体验模式：答题时间已结束，智能体配置不可修改。现在可以进行对话体验与效果验证（老师现场核验用），新对话不计入评审、不会保存。"),
      !chatEnabled && h("div", { class: "callout warn mb16" },
        "⏳ 对话功能暂未开放：老师还没有在后台配置大模型（LLM）。你可以先完成并保存设计，等老师开放后再来测试。"),
      h("div", { class: "card" },
        h("div", { class: "card-title" },
          h("h3", {}, `💬 与「${agent.name || "我的智能体"}」对话`),
          h("div", { class: "row" },
            h("button", { class: "btn btn-ghost btn-sm", onclick: () => { step = 2; draw(); } },
              chatReadOnly ? "📄 查看设计" : "✏️ 修改设计"),
            !chatReadOnly && windowOpen && h("button", { class: "btn btn-ghost btn-sm", onclick: async () => {
              try {
                await api.post("/api/student/agent/chat/clear");
                history = agent.welcome ? [{ role: "assistant", content: agent.welcome, created_at: "" }] : [];
                renderLog();
                toastOk("对话已清空");
              } catch (e) { toastErr(e.message); }
            } }, "🗑️ 清空对话"))),
        log,
        h("div", { class: "chat-input-row mt16" }, input, sendBtn),
        h("p", { class: "small muted mt8" },
          "测试要点：问 2—3 个真实问题，检验回答是否符合设计；不理想就回「修改设计」调整功能与知识资料。")),
    );
  }

  draw();
}

/* ---- OJ 实操考试卡片 ---- */
function buildExamCard(d) {
  const { exam, questions, result, window_open, llm_ready, agent_status, max_total } = d;
  const card = h("div", { class: "card mb16", style: "border-top:3px solid var(--accent)" },
    h("div", { class: "card-title" },
      h("h3", {}, "🧪 实操考试（智能体作品 · OJ）"),
      result && result.status === "done" ? badge(`判题完成 ${result.score} / ${max_total} 分`, "ok")
        : result && result.status === "running" ? badge("AI 判题中…", "warn")
        : result && result.status === "error" ? badge("判题失败", "danger")
        : badge("未提交", "off")),
    !window_open && h("div", { class: "callout warn mb16" },
      `不在实操考试时间范围内（${exam.start_at || "—"} ~ ${exam.end_at || "—"}）。`),
    window_open && agent_status === "draft" && h("div", { class: "callout warn mb16" },
      "请先在下方操作台完成并保存智能体配置，再提交实操考试。"),
    ...questions.map((q) => h("div", { class: "sub-card mb16" },
      h("div", { class: "spread" },
        h("strong", {}, `📋 ${q.title}`),
        h("span", { class: "badge badge-info" }, `满分 ${q.total_score}`)),
      h("p", { class: "small muted", style: "margin:6px 0" }, "场景：" + q.scene),
      h("div", { style: "white-space:pre-wrap;font-size:14px;line-height:1.8" }, q.task_desc),
      h("div", { class: "small mt8" },
        h("strong", {}, "标准测试问题（判题将逐题运行你的智能体作答）："),
        h("ol", { style: "margin:4px 0 0;padding-left:20px" },
          ...q.test_questions.map((t) => h("li", {}, t)))))),
  );

  // 判题结果区
  if (result) {
    if (result.status === "done") {
      card.append(h("div", { class: "card-title mt16" }, h("h3", {}, "🧾 判题结果")),
        h("div", { class: "score-dims mb16" },
          h("div", { class: "score-dim" }, h("div", { class: "v" }, String(result.score)), h("div", { class: "k" }, `实操得分 / ${max_total}`)),
          h("div", { class: "score-dim" }, h("div", { class: "v" }, result.judged_at ? result.judged_at.slice(5, 16) : "—"), h("div", { class: "k" }, "判题时间"))),
        ...result.detail.map((r) => h("div", { class: "sub-card mb8" },
          h("div", { class: "spread" },
            h("strong", { class: "small" }, r.q),
            h("span", { class: "badge " + (r.score >= r.max * 0.8 ? "badge-ok" : r.score > 0 ? "badge-warn" : "badge-danger") },
              `${r.score} / ${r.max} 分`)),
          h("div", { class: "small mt8", style: "white-space:pre-wrap" }, "智能体回答：" + r.agent_reply),
          h("div", { class: "small muted mt8" }, "评分评语：" + (r.comment || "—")))));
    } else if (result.status === "error") {
      card.append(h("div", { class: "callout danger mt16" },
        "❌ 自动判题失败：" + (result.error || "未知原因") + "。请检查智能体配置后重试；若持续失败请联系老师。"));
    } else if (result.status === "running") {
      card.append(h("div", { class: "callout mb16" }, "⏳ 正在运行你的智能体回答标准问题并由 AI 判分，请稍候…（页面会自动刷新）"));
    }
  }

  // 操作区
  const canSubmit = window_open && llm_ready && agent_status !== "draft" &&
                    (!result || (result.status !== "running" && result.status !== "done"));
  if (result && result.status === "done") {
    card.append(h("p", { class: "small muted" }, "判题已完成。如老师重新开放或你修改了配置，可再次提交判题。"),
      h("button", { class: "btn btn-ghost btn-sm", onclick: doSubmit }, "重新提交判题"));
  } else if (canSubmit) {
    card.append(h("div", { class: "row mt16" },
      h("button", { class: "btn btn-lg", onclick: doSubmit }, "📤 自动提交判题"),
      h("span", { class: "small muted" }, "提交后系统将运行你的智能体回答各题标准问题，由 AI 依据评分要点判分（允许部分得分）")));
  } else if (window_open && !llm_ready) {
    card.append(h("p", { class: "small", style: "color:var(--warn)" }, "判题服务未就绪：老师尚未完成大模型配置。"));
  }
  return card;

  async function doSubmit() {
    confirmBox("提交后系统将自动运行你的智能体回答全部标准问题并进行 AI 判分，确认提交？", async () => {
      try {
        await api.post("/api/student/agent-exam/submit");
        toastOk("已提交，AI 判题进行中…");
        render($("#app"));
      } catch (e) { toastErr(e.message); }
    });
  }
}

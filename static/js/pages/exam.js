/** 考试页：服务端计时、自动保存、倒计时、到时自动收卷、切屏记录。 */
import { api } from "../api.js?v=13";
import { h, $, $$, toastOk, toastErr, modal, fmtDur } from "../ui.js?v=13";
import { setNav } from "../app.js?v=13";

let st = null;          // 考试状态
let answers = {};       // {qid: [keys]}
let saveTimer = null;
let tickTimer = null;
let dirty = false;

export async function render(app) {
  setNav("");
  app.innerHTML = "";
  const shell = h("div", { class: "exam-shell" });
  app.append(shell);
  shell.append(h("div", { class: "text-c muted", style: "padding:80px 0" }, "正在进入考试…"));

  try {
    const s0 = await api.get("/api/exam/state");
    if (s0.status === "not_started") {
      await api.post("/api/exam/start");
      st = await api.get("/api/exam/state");
    } else if (s0.status === "submitted") {
      st = s0;
      return renderDone(shell);
    } else {
      st = s0;
    }
  } catch (e) {
    shell.innerHTML = "";
    shell.append(h("div", { class: "card lock-screen" },
      h("div", { style: "font-size:40px" }, "🚫"),
      h("h3", {}, "无法进入考试"),
      h("p", { class: "muted" }, e.message),
      h("a", { class: "btn btn-ghost", href: "#/me" }, "返回工作台")));
    return;
  }

  if (st.status === "submitted") return renderDone(shell);
  answers = { ...(st.answers || {}) };
  renderExam(shell);
  startTimers(shell);
}

/* ---------------- 主界面 ---------------- */
function renderExam(shell) {
  shell.innerHTML = "";
  const answeredCount = () => Object.values(answers).filter((v) => v && v.length).length;

  const timer = h("div", { class: "exam-timer", id: "exam-timer" }, "--:--");
  const saveInd = h("span", { class: "save-ind", id: "save-ind" }, "");
  const topbar = h("div", { class: "exam-topbar" },
    h("div", {},
      h("div", { class: "small", style: "opacity:.75" }, "剩余时间"),
      timer),
    h("div", { class: "exam-meta" },
      `共 ${st.questions.length} 题 · 满分 ${st.total_score} 分 · 已答 `,
      h("b", { id: "ans-count" }, "0"), " 题"),
    h("div", { style: "margin-left:auto", class: "row" }, saveInd,
      h("button", { class: "btn btn-ok", onclick: askSubmit }, "交 卷")),
  );

  const nav = h("div", { class: "q-nav", id: "q-nav" });
  const list = h("div", { id: "q-list" });

  st.questions.forEach((q, i) => {
    nav.append(h("button", { class: "q-dot", id: `dot-${q.id}`, "data-qid": q.id,
      onclick: () => $(`#q-${q.id}`).scrollIntoView({ behavior: "smooth", block: "start" }) }, String(i + 1)));
    list.append(renderQuestion(q, i));
  });

  shell.append(topbar,
    h("div", { class: "callout", style: "margin-top:16px" },
      "作答须知：独立完成作答，不得由他人代答，不得借助通讯工具或他人协助。系统会自动保存答案；考试时间结束将自动收卷。"),
    nav, list,
    h("div", { class: "exam-foot" },
      h("span", { class: "save-ind" }, saveInd.textContent),
      h("button", { class: "btn btn-ok btn-lg", onclick: askSubmit }, "交 卷")),
  );
  updateDots();
}

function renderQuestion(q, idx) {
  const selected = new Set(answers[String(q.id)] || []);
  const typeText = { single: "单选题", multiple: "多选题", judge: "判断题" }[q.type];
  const optsBox = h("div", {});
  for (const o of q.options) {
    const inputType = q.type === "multiple" ? "checkbox" : "radio";
    const opt = h("label", { class: "opt" + (selected.has(o.key) ? " selected" : "") },
      h("input", { type: inputType, name: `q${q.id}`, value: o.key,
        checked: selected.has(o.key),
        onchange: (e) => {
          if (q.type === "multiple") {
            if (e.target.checked) selected.add(o.key); else selected.delete(o.key);
          } else {
            selected.clear(); selected.add(o.key);
          }
          $$(".opt", optsBox).forEach((el, i) => el.classList.toggle("selected", selected.has(q.options[i].key)));
          answers[String(q.id)] = [...selected];
          dirty = true;
          updateDots();
        } }),
      h("span", { class: "key" }, o.key + "."),
      h("span", {}, o.text));
    optsBox.append(opt);
  }
  return h("div", { class: "card q-card", id: `q-${q.id}` },
    h("div", { class: "q-head" },
      h("span", { class: "q-no" }, `第 ${idx + 1} 题`),
      h("span", { class: "q-type" }, typeText + (q.topic ? ` · ${q.topic}` : "")),
      h("span", { class: "q-score" }, `${q.score} 分`)),
    h("div", { class: "q-stem" }, q.stem),
    optsBox);
}

function updateDots() {
  $$(".q-dot").forEach((d) => {
    const a = answers[d.dataset.qid];
    d.classList.toggle("answered", !!(a && a.length));
  });
  const cnt = $("#ans-count");
  if (cnt) cnt.textContent = String(Object.values(answers).filter((v) => v && v.length).length);
}

/* ---------------- 计时 / 自动保存 ---------------- */
function startTimers(shell) {
  clearInterval(tickTimer);
  clearInterval(saveTimer);

  tickTimer = setInterval(async () => {
    const remain = remainSeconds();
    const el = $("#exam-timer");
    if (!el) return stopTimers();
    el.textContent = fmtClock(remain);
    el.classList.toggle("warn", remain <= 300 && remain > 60);
    el.classList.toggle("crit", remain <= 60);
    if (remain <= 0) {
      stopTimers();
      await autoSubmit();
    }
  }, 500);

  saveTimer = setInterval(async () => {
    if (!dirty) return;
    await doSave(false);
  }, 20000);

  window.addEventListener("beforeunload", warnUnload);
  document.addEventListener("visibilitychange", onVisibility);
}

function stopTimers() {
  clearInterval(tickTimer); clearInterval(saveTimer);
  window.removeEventListener("beforeunload", warnUnload);
  document.removeEventListener("visibilitychange", onVisibility);
}

function warnUnload(e) {
  if (st && st.status === "running") { e.preventDefault(); e.returnValue = ""; }
}

async function onVisibility() {
  if (document.hidden && st && st.status === "running") {
    try { await api.post("/api/exam/event", { type: "leave" }); } catch { /* ignore */ }
  }
}

function remainSeconds() {
  const deadline = new Date(st.deadline.replace(" ", "T"));
  return Math.max(0, Math.floor((deadline - Date.now()) / 1000));
}

function fmtClock(sec) {
  const m = Math.floor(sec / 60), s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

async function doSave(notify = true) {
  const ind = $("#save-ind");
  if (ind) ind.textContent = "保存中…";
  try {
    const r = await api.post("/api/exam/save", { answers });
    dirty = false;
    if (ind) ind.textContent = `已自动保存 ${r.saved_count} 题 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
    if (notify) toastOk("答案已保存");
  } catch (e) {
    if (ind) ind.textContent = "保存失败，将于稍后重试";
    if (notify) toastErr(e.message);
  }
}

/* ---------------- 交卷 ---------------- */
function askSubmit() {
  const unanswered = st.questions.length - Object.values(answers).filter((v) => v && v.length).length;
  modal({
    title: "确认交卷？",
    body: h("div", {},
      unanswered > 0
        ? h("p", { style: "color:var(--warn);font-weight:600" }, `还有 ${unanswered} 题未作答，交卷后未答题不得分。`)
        : h("p", {}, "所有题目均已作答。"),
      h("p", { class: "small muted" },
        st.allow_resubmit ? "交卷后在考试截止前仍可恢复作答并再次提交，成绩以最后一次提交为准。" : "交卷后不可再修改。")),
    actions: (close) => [
      h("button", { class: "btn btn-ghost", onclick: () => { close(); doSave(false); } }, "继续作答"),
      h("button", { class: "btn btn-ok", onclick: () => { close(); doSubmit(false); } }, "确认交卷"),
    ],
  });
}

async function autoSubmit() {
  toastErr("考试时间已到，正在自动收卷…", 5000);
  await doSubmit(true);
}

async function doSubmit(forced) {
  stopTimers();
  try {
    const r = await api.post("/api/exam/submit", { answers });
    st.status = "submitted";
    st.score = r.score;
    st.duration_seconds = r.duration_seconds;
    toastOk(`交卷成功！得分 ${r.score}`);
    const shell = $("#app").querySelector(".exam-shell") || $("#app");
    shell.innerHTML = "";
    renderDone(shell);
  } catch (e) {
    if (String(e.message).includes("已交卷")) {
      st.status = "submitted";
      renderDone($("#app").querySelector(".exam-shell") || $("#app"));
    } else {
      toastErr(e.message);
      startTimers($("#app").querySelector(".exam-shell"));
    }
  }
}

function renderDone(shell) {
  stopTimers();
  shell.innerHTML = "";
  // 恢复作答按钮：仅当允许重复提交且考试窗口截止时间未过时显示（恢复后会重发一个考试时钟）
  const canResume = st.allow_resubmit && st.window_end && new Date(st.window_end.replace(" ", "T")) > new Date();
  shell.append(h("div", { class: "card lock-screen" },
    h("div", { style: "font-size:52px" }, "🎉"),
    h("h2", {}, "已完成作答"),
    st.score != null && st.show_score_after
      ? h("div", { class: "score-dims", style: "max-width:460px;margin:20px auto" },
          h("div", { class: "score-dim" }, h("div", { class: "v" }, String(st.score)), h("div", { class: "k" }, "本次得分")),
          h("div", { class: "score-dim" }, h("div", { class: "v" }, fmtDur(st.duration_seconds).replace(/分.*/, "分")), h("div", { class: "k" }, "完成用时")))
      : h("p", { class: "muted" }, "答卷已提交，成绩由组委会统一评定后公示。"),
    canResume
      ? h("button", {
          class: "btn btn-ghost mt16", onclick: async () => {
            try {
              await api.post("/api/exam/resume");
              toastOk("已恢复作答，成绩以最后一次提交为准");
              render($("#app"));
            } catch (e) { toastErr(e.message); }
          } }, "恢复作答（重新提交以最后一次为准）")
      : h("p", { class: "small muted mt16" }, "本场考试已结束，不能再修改答卷。"),
    h("div", { class: "mt16" }, h("a", { class: "btn", href: "#/me" }, "返回工作台")),
  ));
}

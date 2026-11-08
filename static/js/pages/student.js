/** 我的工作台（学生端）：线上答题 + 设计智能体任务 + 成绩展示。 */
import { api } from "../api.js?v=13";
import { h, $, $$, toastOk, toastErr, modal, confirmBox, badge, fmtTime, lightbox, statusBadge } from "../ui.js?v=13";
import { state, setNav, GROUP_NAMES } from "../app.js?v=13";

const MIN_DESC = 100;

export async function render(app) {
  setNav("我的工作台");
  const data = await api.get("/api/student/overview");
  state.student = { ...state.student, ...data.student };
  app.innerHTML = "";

  const st = data.student;
  /* ---- 选手信息卡 ---- */
  app.append(h("div", { class: "card mb16" },
    h("div", { class: "spread" },
      h("div", { class: "info-list", style: "flex:1;min-width:260px" },
        info("参赛编号", st.entry_no), info("姓名", st.name), info("学校", st.school),
        info("年级", st.grade), info("组别", GROUP_NAMES[st.group_code]), info("指导教师", st.teacher_name || "—")),
      h("div", { class: "row" },
        statusBadge(st.status, st.disqualified ? "disqualified" : null),
        st.edit_locked && badge("已锁定", "warn")),
    ),
  ));

  if (st.disqualified) {
    app.append(h("div", { class: "card", style: "border-left:4px solid var(--danger)" },
      h("h3", {}, "⚠️ 参赛资格说明"),
      h("p", { class: "muted" }, "经组委会核实，本选手存在违规情形，已按竞赛规则处理。如有疑问请联系组委会。")));
    return;
  }

  await renderExamGroup(app, data);

  await renderAgentCard(app);
  renderScoreSection(app, data);
}

/* ---- 设计智能体入口 ---- */
async function renderAgentCard(app) {
  let info;
  try { info = await api.get("/api/student/task"); } catch { return; }
  const a = info.agent;
  const submitted = a && a.status === "submitted";
  const locked = a && a.check_status === "ok";
  const revise = a && a.check_status === "revise";
  const statusText = !a ? "未开始" : a.status === "submitted" ? "已提交" : "设计中";
  const statusType = a?.status === "submitted" ? "ok" : a ? "info" : "warn";
  const desc = !a ? "根据题目要求，围绕便民场景设计一个属于你的智能体，并与它对话测试"
    : locked ? `「${a.name}」已检测合格并锁定`
    : revise ? `「${a.name}」老师要求修改：${a.check_comment || "请查看备注"}`
    : submitted ? `「${a.name}」已提交，等待老师检测`
    : `「${a.name}」设计中 · 可继续编辑或交任务`;
  app.append(h("div", { class: "card mb16", style: "cursor:pointer",
    onclick: () => { location.hash = "#/agent"; } },
    h("div", { class: "spread" },
      h("div", {},
        h("div", { class: "card-title", style: "margin-bottom:8px" }, h("h3", {}, "🤖 设计智能体")),
        h("p", { class: "small muted", style: "margin:0" }, desc)),
      h("div", { class: "row" },
        badge(statusText, statusType),
        locked && badge("检测合格", "ok"),
        revise && badge("需修改", "warn"),
        h("button", { class: "btn btn-sm" }, a ? "继续 →" : "开始 →")))));
}

function info(k, v) {
  return h("div", {}, h("div", { class: "k" }, k), h("div", { class: "v" }, v));
}

/* ================= 高段/中学组：考试入口 ================= */
function renderExamGroup(app, data) {
  const st = data.student;
  const cfg = data.exam || {};
  const attempt = data.attempt;
  const card = h("div", { class: "card mb16" });
  app.append(card);

  const started = !!attempt;
  const done = attempt && attempt.status === "submitted";
  const inWindow = cfg.enabled && windowOpen(cfg);

  card.append(h("div", { class: "card-title" }, h("h3", {}, `📝 ${GROUP_NAMES[st.group_code]} · 线上作答`)));

  if (!cfg.enabled) {
    card.append(h("div", { class: "lock-screen" },
      h("div", { style: "font-size:40px" }, "🗓️"),
      h("p", { class: "muted" }, "本场考试暂未开放，请关注组委会通知的考试时间。")));
    return;
  }

  card.append(h("div", { class: "info-list mb16" },
    info("开始时间", cfg.start_at || "—"),
    info("截止时间", cfg.end_at || "—"),
    info("作答时长", `${cfg.duration_minutes || "—"} 分钟`),
    info("可否重复提交", cfg.allow_resubmit ? "截止前可再次作答" : "仅一次提交")));

  if (done) {
    // 恢复作答：需同时满足 允许重复提交 + 考试窗口未结束（恢复后会重发一个考试时钟）
    const attemptOpen = cfg.allow_resubmit && cfg.end_at && new Date(cfg.end_at.replace(" ", "T")) > new Date();
    card.append(h("div", { class: "row" },
      badge("已交卷", "ok"),
      h("span", { class: "small muted" },
        `提交时间 ${fmtTime(attempt.submitted_at)} · 用时 ${Math.floor((attempt.duration_seconds || 0) / 60)} 分钟` +
        (cfg.allow_resubmit && attemptOpen ? " · 截止前可恢复作答并再次提交（以最后一次为准）" : " · 考试已结束")),
      cfg.allow_resubmit && attemptOpen &&
      h("button", { class: "btn btn-ghost", onclick: () => location.hash = "#/exam" }, "恢复作答"),
    ));
  } else if (started) {
    card.append(h("div", { class: "row" },
      badge("作答进行中", "warn"),
      h("span", { class: "small muted" }, `截止：${fmtTime(attempt.deadline)} · 到时自动收卷`),
      h("button", { class: "btn", onclick: () => location.hash = "#/exam" }, "继续作答 →")));
  } else if (inWindow) {
    card.append(h("div", { class: "row" },
      badge("考试进行中", "ok"),
      h("button", { class: "btn btn-lg", onclick: () => {
        confirmBox("进入考试后立即开始计时，作答期间请勿关闭或刷新页面。现在开始吗？", () => {
          location.hash = "#/exam";
        }, { yes: "开始作答" });
      } }, "进入考试"),
    ));
    card.append(h("p", { class: "small muted mt16" },
      "作答须知：独立完成，不得由他人代答；不得借助通讯工具或他人协助；系统记录异常行为作为佐证。"));
  } else {
    card.append(h("p", { class: "muted" },
      `考试时间：${cfg.start_at || "—"} 至 ${cfg.end_at || "—"}。请在规定时间内进入作答。`));
  }
}

function windowOpen(cfg) {
  if (!cfg.start_at || !cfg.end_at) return false;
  const now = nowLocal();
  return cfg.start_at.slice(0, 16) <= now && now <= cfg.end_at.slice(0, 16);
}

function nowLocal() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ================= 成绩区 ================= */
function renderScoreSection(app, data) {
  if (!data.publish.published) return;
  const box = h("div", { class: "card mt16" },
    h("div", { class: "card-title" }, h("h3", {}, "🏅 我的初赛成绩")));
  if (data.publish.score) {
    const s = data.publish.score;
    box.append(h("div", { class: "score-dims" },
      h("div", { class: "score-dim" }, h("div", { class: "v" }, String(s.score)), h("div", { class: "k" }, "得分")),
      h("div", { class: "score-dim" }, h("div", { class: "v" }, String(s.rank)), h("div", { class: "k" }, "组别名次")),
      h("div", { class: "score-dim" }, h("div", { class: "v" }, String(s.duration_seconds ?? "—")), h("div", { class: "k" }, "用时（秒）"))));
  } else {
    box.append(h("p", { class: "muted" }, "成绩已开放公示，但你的材料尚未进入排名（未提交或未评审核）。"));
  }
  app.append(box);
}

/* ================= 公共小部件 ================= */
function dropzone(text, sub, onFile) {
  const fileInput = h("input", { type: "file", accept: "image/png,image/jpeg", style: "display:none",
    onchange: (e) => { onFile(e.target.files[0]); e.target.value = ""; } });
  const zone = h("div", { class: "dropzone", tabindex: "0", role: "button",
    onclick: () => fileInput.click(),
    onkeydown: (e) => { if (e.key === "Enter") fileInput.click(); },
    ondragover: (e) => { e.preventDefault(); zone.classList.add("drag"); },
    ondragleave: () => zone.classList.remove("drag"),
    ondrop: (e) => { e.preventDefault(); zone.classList.remove("drag"); onFile(e.dataTransfer.files[0]); } },
    h("div", { class: "icon" }, "🖼️"), h("p", {}, text), h("div", { class: "sub" }, sub), fileInput);
  return zone;
}

function imageDims(file) {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { resolve({ w: img.naturalWidth, h: img.naturalHeight }); URL.revokeObjectURL(url); };
    img.onerror = () => { resolve(null); URL.revokeObjectURL(url); };
    img.src = url;
  });
}

/** 我的工作台（学生端）：线上答题 + 设计智能体任务 + 成绩展示。 */
import { api } from "../api.js?v=12";
import { h, $, $$, toastOk, toastErr, modal, confirmBox, badge, fmtTime, lightbox, statusBadge } from "../ui.js?v=12";
import { state, setNav, GROUP_NAMES } from "../app.js?v=12";

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

  if (st.group_code === "low") await renderLow(app, data);
  else await renderExamGroup(app, data);

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

/* ================= 小学低段组：作品提交向导 ================= */
function renderLow(app, data) {
  const st = data.student;
  const subs = data.submission;
  const submitted = st.status === "submitted";
  const locked = submitted && !subs.allow_retract;

  const deadlineCard = h("div", { class: "card mb16" },
    h("div", { class: "spread" },
      h("div", { class: "row" },
        badge(subs.open ? "提交通道开放中" : "提交通道已关闭", subs.open ? "ok" : "off"),
        subs.deadline && h("span", { class: "small muted" }, `截止时间：${fmtTime(subs.deadline)}`)),
      h("div", { class: "row" },
        submitted && !st.edit_locked && subs.open && subs.allow_retract &&
        h("button", { class: "btn btn-ghost btn-sm", onclick: doRetract }, "撤回修改"),
        submitted && h("button", { class: "btn btn-ghost btn-sm", onclick: previewSubmit }, "查看提交内容")),
    ),
    h("p", { class: "small muted", style: "margin:8px 0 0" },
      "按要求提交：① 创意设计图 1 张（PNG/JPG，≥1920×1080，≤20MB，AI 生成）；② 作品说明 ≥100 字并标注 AI 平台；③ 创作过程记录 1—3 张。"),
  );
  app.append(deadlineCard);

  if (submitted) {
    app.append(h("div", { class: "card", style: "border-left:4px solid var(--ok)" },
      h("h3", {}, "✅ 作品已提交"),
      h("p", { class: "muted", style: "margin:0" }, `提交时间：${fmtTime(st.submitted_at)}。请耐心等待评审，成绩将在公示期开放查询。`),
    ));
    return;
  }

  if (!subs.open || (subs.deadline && fmtTime(subs.deadline) < nowLocal())) {
    app.append(h("div", { class: "card text-c", style: "padding:40px" },
      h("div", { style: "font-size:40px" }, "⏰"),
      h("h3", {}, subs.open ? "已过提交截止时间" : "作品提交通道未开放"),
      h("p", { class: "muted" }, subs.open ? `截止时间：${fmtTime(subs.deadline)}` : "请关注组委会通知。")));
    return;
  }

  /* 向导 */
  let step = 1;
  const stepsBar = h("div", { class: "steps" });
  const body = h("div", {});
  const card = h("div", { class: "card" }, stepsBar, body);
  app.append(card);

  const draft = {
    work_title: st.work_title || "",
    ai_platform: st.ai_platform || "",
    description: st.description || "",
    design_image: st.design_image || "",
    process_images: st.process_images || [],
  };

  function drawSteps() {
    stepsBar.innerHTML = "";
    ["作品信息", "创意设计图", "过程记录与提交"].forEach((lbl, i) => {
      const n = i + 1;
      stepsBar.append(h("div", { class: `step ${n < step ? "done" : n === step ? "active" : ""}` },
        h("div", { class: "dot" }, n < step ? "✓" : String(n)),
        h("div", { class: "lbl" }, lbl)));
    });
  }

  function redraw() {
    drawSteps();
    body.innerHTML = "";
    if (step === 1) body.append(step1());
    if (step === 2) body.append(step2());
    if (step === 3) body.append(step3());
  }

  /* 步骤 1：作品信息 */
  function step1() {
    const descArea = h("textarea", { class: "textarea", rows: 7, placeholder:
      "写明：作品名称、应用场景、所解决的便民问题、功能设计、创意亮点…（不少于 100 字）" });
    descArea.value = draft.description;
    const count = h("div", { class: "char-count" });
    const updateCount = () => {
      const n = descArea.value.trim().length;
      count.textContent = `${n} 字` + (n >= MIN_DESC ? " ✓ 已达标" : `（还差 ${MIN_DESC - n} 字）`);
      count.classList.toggle("ok", n >= MIN_DESC);
    };
    descArea.addEventListener("input", updateCount); updateCount();

    const title = h("input", { class: "input", maxlength: 60, placeholder: "如：智能感应遮阳路灯" });
    title.value = draft.work_title;
    const platform = h("input", { class: "input", maxlength: 60, placeholder: "如实填写，如：即梦 AI / 文心一格 / 豆包…" });
    platform.value = draft.ai_platform;

    async function save(goNext) {
      draft.work_title = title.value.trim();
      draft.description = descArea.value.trim();
      draft.ai_platform = platform.value.trim();
      try {
        await api.put("/api/student/work", { work_title: draft.work_title, ai_platform: draft.ai_platform, description: draft.description });
        if (goNext) { step = 2; redraw(); }
        else toastOk("已保存草稿");
      } catch (e) { toastErr(e.message); }
    }

    return h("div", {},
      h("div", { class: "field" }, h("label", { class: "req" }, "作品名称"), title),
      h("div", { class: "field" },
        h("label", { class: "req" }, "作品说明（≥100 字）"), descArea, count,
        h("p", { class: "hint" }, "请写明应用场景、所解决的便民问题、功能设计与创意亮点。")),
      h("div", { class: "field" },
        h("label", { class: "req" }, "所使用的人工智能创作平台"),
        platform, h("p", { class: "hint" }, "须如实标注，未标注将影响评审。")),
      h("div", { class: "row", style: "justify-content:flex-end" },
        h("button", { class: "btn btn-ghost", onclick: () => save(false) }, "保存草稿"),
        h("button", { class: "btn", onclick: () => save(true) }, "下一步：上传设计图 →")),
    );
  }

  /* 步骤 2：设计图上传 */
  function step2() {
    const preview = h("div", { class: "preview-grid" });
    const drop = dropzone("点击或拖拽上传创意设计图", "PNG / JPG · ≥1920×1080 · ≤20MB", pick);

    async function pick(file) {
      if (!file) return;
      if (!/image\/(png|jpeg)/i.test(file.type) && !/\.(png|jpe?g)$/i.test(file.name)) {
        toastErr("仅支持 PNG/JPG 格式"); return;
      }
      if (file.size > 20 * 1024 * 1024) { toastErr("文件超过 20MB"); return; }
      const dims = await imageDims(file);
      if (!dims || dims.w < 1920 || dims.h < 1080) {
        toastErr(`设计图尺寸不达标：当前 ${dims ? dims.w + "×" + dims.h : "未知"}，要求 ≥1920×1080`);
        return;
      }
      const fd = new FormData(); fd.append("file", file);
      try {
        const r = await api.upload("/api/student/design-image", fd);
        draft.design_image = r.path;
        drawPreview();
        toastOk(`设计图上传成功（${r.w}×${r.h}）`);
      } catch (e) { toastErr(e.message); }
    }

    function drawPreview() {
      preview.innerHTML = "";
      if (draft.design_image) {
        const url = "/uploads/" + draft.design_image;
        preview.append(h("div", { class: "preview" },
          h("img", { src: url, onclick: () => lightbox(url) }),
          h("span", { class: "ok-badge" }, "创意设计图"),
          h("button", { class: "rm", title: "删除", onclick: async () => {
            confirmBox("确定删除设计图？", async () => {
              try { await api.del("/api/student/design-image"); draft.design_image = ""; drawPreview(); }
              catch (e) { toastErr(e.message); }
            }, { danger: true });
          } }, "×")));
      }
    }
    drawPreview();

    return h("div", {},
      h("div", { class: "callout" }, "设计图须包含设施主体造型及其所处场景，能够清晰体现设施的功能定位与使用方式。"),
      !draft.design_image && drop, preview,
      h("div", { class: "row mt16", style: "justify-content:space-between" },
        h("button", { class: "btn btn-ghost", onclick: () => { step = 1; redraw(); } }, "← 上一步"),
        h("button", { class: "btn", disabled: !draft.design_image, onclick: () => { step = 3; redraw(); } }, "下一步：过程记录 →")),
    );
  }

  /* 步骤 3：过程记录 + 提交 */
  function step3() {
    const grid = h("div", { class: "preview-grid" });
    const drop = h("div", { class: "dropzone", onclick: () => fileInput.click(),
      ondragover: (e) => { e.preventDefault(); drop.classList.add("drag"); },
      ondragleave: () => drop.classList.remove("drag"),
      ondrop: (e) => { e.preventDefault(); drop.classList.remove("drag"); pick(e.dataTransfer.files[0]); },
      style: (draft.process_images.length >= 3) ? "display:none" : "" },
      h("div", { class: "icon" }, "📸"),
      h("p", {}, "点击或拖拽上传创作过程记录"),
      h("div", { class: "sub" }, `截图 / 草图 / 照片 · ${draft.process_images.length}/3 张 · 单张 ≤20MB`));
    const fileInput = h("input", { type: "file", accept: "image/png,image/jpeg", style: "display:none",
      onchange: (e) => { pick(e.target.files[0]); e.target.value = ""; } });

    async function pick(file) {
      if (!file) return;
      if (!/\.(png|jpe?g)$/i.test(file.name) && !/image\/(png|jpeg)/i.test(file.type)) { toastErr("仅支持 PNG/JPG 格式"); return; }
      if (file.size > 20 * 1024 * 1024) { toastErr("文件超过 20MB"); return; }
      const fd = new FormData(); fd.append("file", file);
      try {
        const r = await api.upload("/api/student/process-image", fd);
        draft.process_images.push(r.path);
        draw();
        toastOk("过程记录已上传");
      } catch (e) { toastErr(e.message); }
    }

    function draw() {
      grid.innerHTML = "";
      draft.process_images.forEach((p, i) => {
        grid.append(h("div", { class: "preview" },
          h("span", { class: "idx-badge" }, `过程记录 ${i + 1}`),
          h("img", { src: "/uploads/" + p, onclick: () => lightbox("/uploads/" + p) }),
          h("button", { class: "rm", onclick: async () => {
            confirmBox("删除这张过程记录？", async () => {
              try {
                await api.del(`/api/student/process-image/${i}`);
                draft.process_images.splice(i, 1);
                drop.style.display = draft.process_images.length >= 3 ? "none" : "";
                draw();
              } catch (e) { toastErr(e.message); }
            }, { danger: true });
          } }, "×")));
      });
    }
    draw();

    return h("div", {},
      h("div", { class: "field" },
        h("label", { class: "req" }, "创作过程记录（1—3 张）"),
        drop, fileInput, grid,
        h("p", { class: "hint" }, "可为与 AI 创作平台的交互记录截图、构思草图或绘制过程照片，须真实完整。")),
      h("div", { class: "row", style: "justify-content:space-between" },
        h("button", { class: "btn btn-ghost", onclick: () => { step = 2; redraw(); } }, "← 上一步"),
        h("button", { class: "btn btn-lg", onclick: doSubmit }, "提交作品 ✓")),
    );
  }

  async function doSubmit() {
    const missing = [];
    if (!draft.work_title.trim()) missing.push("作品名称");
    if (draft.description.trim().length < MIN_DESC) missing.push(`作品说明 ≥${MIN_DESC} 字`);
    if (!draft.ai_platform.trim()) missing.push("AI 平台标注");
    if (!draft.design_image) missing.push("创意设计图");
    if (draft.process_images.length < 1) missing.push("创作过程记录（1—3 张）");
    if (missing.length) { toastErr("请补全：" + missing.join("、")); return; }
    modal({
      title: "确认提交作品？",
      body: h("div", {},
        h("p", {}, "提交后将进入评审流程。请在提交前确认所有材料真实、完整、符合要求。"),
        h("p", { class: "small muted" }, "提交后如需修改，可在截止前「撤回修改」（若组委开放撤回）。")),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "再检查一下"),
        h("button", { class: "btn", onclick: async () => {
          close();
          try { await api.post("/api/student/submit"); toastOk("提交成功！"); render(app); }
          catch (e) { toastErr(e.message); }
        } }, "确认提交"),
      ],
    });
  }

  async function doRetract() {
    confirmBox("撤回后作品回到草稿状态，可继续修改后再次提交。确定撤回？", async () => {
      try { await api.post("/api/student/retract"); toastOk("已撤回，可继续修改"); render(app); }
      catch (e) { toastErr(e.message); }
    });
  }

  function previewSubmit() {
    modal({
      title: `作品材料 · ${st.entry_no}`,
      wide: true,
      body: h("div", {},
        h("div", { class: "kv" },
          h("div", { class: "k" }, "作品名称"), h("div", {}, st.work_title),
          h("div", { class: "k" }, "AI 平台"), h("div", {}, st.ai_platform),
          h("div", { class: "k" }, "作品说明"), h("div", { style: "white-space:pre-wrap" }, st.description),
          h("div", { class: "k" }, "提交时间"), h("div", {}, fmtTime(st.submitted_at))),
        st.design_image && h("img", { src: "/uploads/" + st.design_image, style: "border-radius:10px;margin-top:12px", onclick: () => lightbox("/uploads/" + st.design_image) }),
      ),
      actions: (close) => [h("button", { class: "btn", onclick: close }, "关闭")],
    });
  }

  redraw();  // 初始绘制向导（此前遗漏，导致撤回后向导空白）
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
    if (data.student.group_code === "low") {
      box.append(h("div", { class: "score-dims" },
        ...[["s_theme", "主题契合"], ["s_creative", "创意构思"], ["s_expression", "设计表达"], ["s_process", "创作过程"], ["total", "总分"]]
          .map(([k, lbl]) => h("div", { class: "score-dim" },
            h("div", { class: "v" }, String(s[k] ?? "—")), h("div", { class: "k" }, lbl)))));
    } else {
      box.append(h("div", { class: "score-dims" },
        h("div", { class: "score-dim" }, h("div", { class: "v" }, String(s.score)), h("div", { class: "k" }, "得分")),
        h("div", { class: "score-dim" }, h("div", { class: "v" }, String(s.rank)), h("div", { class: "k" }, "组别名次")),
        h("div", { class: "score-dim" }, h("div", { class: "v" }, String(s.duration_seconds ?? "—")), h("div", { class: "k" }, "用时（秒）"))));
    }
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

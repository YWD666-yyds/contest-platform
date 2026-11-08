/** 管理后台：概览 / 学生 / 题库 / 赛事设置 / 成绩公示 / 评委 / 公告 / 日志。 */
import { api, download } from "../api.js?v=13";
import { h, $, $$, toastOk, toastErr, modal, confirmBox, badge, fmtTime, fmtDur, empty, copyText, dropdown } from "../ui.js?v=13";
import { setNav, GROUP_NAMES } from "../app.js?v=13";

let currentTab = "overview";

export async function render(app) {
  setNav("管理后台");
  if (location.hash.includes("/")) {
    const m = location.hash.match(/#\/admin\/(\w+)/);
    if (m) currentTab = m[1];
  }
  app.innerHTML = "";
  const side = h("div", { class: "admin-side" });
  const content = h("div", {});
  const tabs = [
    ["overview", "📊 概览"],
    ["students", "👥 学生管理"],
    ["questions", "📚 题库管理"],
    ["settings", "⚙️ 赛事设置"],
    ["agent", "🤖 智能体设置"],
    ["agenttask", "🗂️ 智能体任务"],
    ["exam", "🧪 实操考试"],
    ["scores", "🏅 成绩与公示"],
    ["announcements", "📢 公告管理"],
    ["logs", "📋 审计日志"],
  ];
  for (const [key, label] of tabs) {
    side.append(h("a", { href: `#/admin/${key}`, class: currentTab === key ? "active" : "",
      onclick: () => { currentTab = key; setTimeout(loadTab, 0); } }, label));
  }
  app.append(h("div", { class: "admin-layout" }, side, content));
  await loadTab(content);
}

async function loadTab(content) {
  content.innerHTML = "";
  content.append(h("div", { class: "text-c muted", style: "padding:60px" }, "加载中…"));
  const renderers = {
    overview: tabOverview, students: tabStudents, questions: tabQuestions,
    settings: tabSettings, agent: tabAgent, agenttask: tabAgentTask, exam: tabExam, scores: tabScores, judges: tabJudges,
    announcements: tabAnnouncements, logs: tabLogs,
  };
  try {
    content.innerHTML = "";
    await renderers[currentTab](content);
  } catch (e) {
    content.innerHTML = "";
    content.append(empty("加载失败：" + e.message));
  }
}

/* ================= 概览 ================= */
async function tabOverview(el) {
  const data = await api.get("/api/admin/overview");
  el.append(h("h2", { style: "margin-bottom:14px" }, "赛事概览"));
  const groups = ["high"];
  el.append(h("div", { class: "grid grid-3 mb16" },
    ...groups.map((g) => {
      const s = data.stats[g];
      return h("div", { class: "card" },
        h("div", { class: "spread" },
          h("strong", {}, GROUP_NAMES[g]),
          g === "low"
            ? badge("作品评审制", "info")
            : badge("线上答题", "info")),
        h("div", { class: "info-list mt8" },
          h("div", {}, h("div", { class: "k muted small" }, "报名人数"), h("div", { class: "v", style: "font-size:22px" }, String(s.total))),
          h("div", {}, h("div", { class: "k muted small" }, g === "low" ? "已提交作品" : "已交卷"), h("div", { class: "v", style: "font-size:22px" }, String(g === "low" ? s.submitted : s.attempt_submitted || 0))),
          h("div", {}, h("div", { class: "k muted small" }, g === "low" ? "已评审核" : "报名但未交卷"), h("div", { class: "v", style: "font-size:22px" }, g === "low" ? String(s.graded || 0) : String(s.total - (s.attempt_submitted || 0))))));
    })));

  el.append(h("div", { class: "grid grid-2" },
    h("div", { class: "card" },
      h("div", { class: "card-title" }, h("h3", {}, "提交通道")),
      h("div", { class: "row" },
        badge(data.settings.submission.open ? "开放中" : "已关闭", data.settings.submission.open ? "ok" : "off"),
        data.settings.submission.deadline && h("span", { class: "small muted" }, `截止 ${fmtTime(data.settings.submission.deadline)}`)),
      h("p", { class: "small muted mt8" },
        `智能体任务：已提交 ${data.agent_stats?.submitted ?? 0} 人（合格 ${data.agent_stats?.ok ?? 0} 人） · 评审由组委会教师线下开展`)),
    h("div", { class: "card" },
      h("div", { class: "card-title" }, h("h3", {}, "考试安排")),
      ...["high"].map((g) => {
        const c = data.settings.exams[g] || {};
        return h("div", { class: "row mb8" },
          badge(c.enabled ? "已启用" : "未启用", c.enabled ? "ok" : "off"),
          h("span", { class: "small" }, `${GROUP_NAMES[g]}：${c.start_at || "—"} ~ ${c.end_at || "—"} · ${c.duration_minutes || "?"} 分钟`));
      })),
  ));
}

/* ================= 学生管理 ================= */
async function tabStudents(el) {
  let filters = { group: "", q: "", status: "", page: 1 };

  const fGroup = dropdown({ options: [{ v: "", t: "全部组别" }, ...Object.entries(GROUP_NAMES).map(([k, v]) => ({ v: k, t: v }))] });
  const fStatus = dropdown({ options: [{ v: "", t: "全部状态" }, { v: "draft", t: "未提交" }, { v: "submitted", t: "已提交" }] });
  fGroup.style.width = "150px";
  fStatus.style.width = "130px";

  const bar = h("div", { class: "filter-bar" },
    fGroup,
    h("input", { class: "input", id: "f-q", placeholder: "搜索姓名/学校/参赛编号", style: "width:220px",
      onkeydown: (e) => { if (e.key === "Enter") apply(); } }),
    fStatus,
    h("button", { class: "btn btn-sm", onclick: apply }, "查询"),
    h("span", { style: "flex:1" }),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => showImport() }, "📥 批量导入"),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => showCreate() }, "＋ 单个添加"),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => download("/api/admin/students/export" + (filters.group ? `?group=${filters.group}` : "")) }, "⬇️ 导出 CSV"),
  );

  const listBox = h("div", {});
  el.append(bar, listBox);

  function readFilters() {
    filters.group = fGroup.getValue();
    filters.q = $("#f-q", el).value.trim();
    filters.status = fStatus.getValue();
  }
  function apply() { readFilters(); filters.page = 1; load(); }

  async function load() {
    listBox.innerHTML = "";
    listBox.append(h("div", { class: "text-c muted", style: "padding:30px" }, "加载中…"));
    const params = new URLSearchParams({ page: filters.page, size: 20 });
    if (filters.group) params.set("group", filters.group);
    if (filters.q) params.set("q", filters.q);
    if (filters.status) params.set("status", filters.status);
    const data = await api.get(`/api/admin/students?${params}`);
    listBox.innerHTML = "";
    if (!data.items.length) { listBox.append(empty("没有符合条件的学生")); return; }

    listBox.append(h("div", { class: "tablewrap" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {},
        ..."参赛编号 姓名 学校 年级 组别 指导教师 提交状态 评分/得分 操作".split(" ").map((c) => h("th", {}, c)))),
      h("tbody", {}, ...data.items.map((r) => h("tr", {},
        h("td", { class: "nowrap" }, r.entry_no),
        h("td", { class: "nowrap" }, r.name, r.disqualified ? h("span", { class: "badge badge-danger", style: "margin-left:5px" }, "取消资格") : "", r.edit_locked ? h("span", { class: "badge badge-warn", style: "margin-left:5px" }, "锁定") : ""),
        h("td", {}, r.school),
        h("td", { class: "nowrap" }, r.grade),
        h("td", { class: "nowrap" }, GROUP_NAMES[r.group_code]),
        h("td", { class: "nowrap" }, r.teacher_name || "—"),
        h("td", {}, statusCell(r)),
        h("td", { class: "nowrap" }, scoreCell(r)),
        h("td", {}, h("div", { class: "row", style: "gap:5px" },
          h("button", { class: "btn btn-ghost btn-sm", onclick: () => editStudent(r, load) }, "编辑"),
          h("button", { class: "btn btn-ghost btn-sm", onclick: () => resetPwd(r) }, "重置密码"),
          h("button", { class: "btn btn-ghost btn-sm", style: "color:var(--danger)", onclick: () => {
            confirmBox(`确定删除 ${r.name}（${r.entry_no}）？此操作不可恢复，将同时删除其提交与成绩。`, async () => {
              await api.del(`/api/admin/students/${r.id}`); toastOk("已删除"); load();
            }, { danger: true, yes: "删除" });
          } }, "删除")))))))));

    const pages = Math.max(1, Math.ceil(data.total / data.size));
    listBox.append(h("div", { class: "pager" },
      h("span", {}, `共 ${data.total} 人`),
      h("button", { class: "btn btn-ghost btn-sm", disabled: filters.page <= 1, onclick: () => { filters.page--; load(); } }, "上一页"),
      h("span", {}, `${filters.page} / ${pages}`),
      h("button", { class: "btn btn-ghost btn-sm", disabled: filters.page >= pages, onclick: () => { filters.page++; load(); } }, "下一页")));
  }

  function statusCell(r) {
    return badge(
      r.attempt_status === "submitted" ? "已交卷" : r.attempt_status === "running" ? "作答中" : "未开考",
      r.attempt_status === "submitted" ? "ok" : r.attempt_status === "running" ? "warn" : "off");
  }
  function scoreCell(r) {
    return r.exam_score != null
      ? h("span", { class: "num" }, `${r.exam_score} 分 · ${fmtDur(r.duration_seconds)}`)
      : h("span", { class: "muted" }, "—");
  }

  await load();

  function editStudent(r, done) {
    const name = h("input", { class: "input", value: r.name });
    const school = h("input", { class: "input", value: r.school });
    const grade = h("input", { class: "input", value: r.grade });
    const teacher = h("input", { class: "input", value: r.teacher_name || "" });
    const lock = h("input", { type: "checkbox", checked: r.edit_locked });
    const dq = h("input", { type: "checkbox", checked: r.disqualified });
    const dqReason = h("input", { class: "input", value: r.disqualify_reason || "", placeholder: "取消资格原因（可选）" });
    modal({
      title: `编辑学生 · ${r.entry_no}`,
      body: h("div", {},
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", {}, "姓名"), name),
          h("div", { class: "field" }, h("label", {}, "学校"), school)),
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", {}, "年级"), grade),
          h("div", { class: "field" }, h("label", {}, "指导教师"), teacher)),
        h("div", { class: "row mb8" }, h("label", { class: "row", style: "gap:6px" }, lock, " 锁定资料（禁止学生修改）")),
        h("div", { class: "row mb8" }, h("label", { class: "row", style: "gap:6px" }, dq, " 取消参赛资格（规则否决项）")),
        dqReason),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          try {
            await api.put(`/api/admin/students/${r.id}`, {
              name: name.value.trim(), school: school.value.trim(), grade: grade.value.trim(),
              teacher_name: teacher.value.trim(), edit_locked: lock.checked,
              disqualified: dq.checked, disqualify_reason: dqReason.value.trim(),
            });
            toastOk("已保存"); close(); done();
          } catch (e) { toastErr(e.message); }
        } }, "保存"),
      ],
    });
  }

  async function resetPwd(r) {
    confirmBox(`为 ${r.name}（${r.entry_no}）重置密码？`, async () => {
      try {
        const res = await api.post(`/api/admin/students/${r.id}/reset-password`);
        showPasswordModal(`新密码（仅显示一次）`, r.entry_no, res.new_password);
      } catch (e) { toastErr(e.message); }
    });
  }

  function showCreate() {
    const name = h("input", { class: "input" });
    const school = h("input", { class: "input" });
    const grade = h("input", { class: "input", placeholder: "如：三年级 / 初一 / 高一" });
    const group = h("input", { class: "input", placeholder: "仅三年级选报高段组时填「高段组」" });
    const teacher = h("input", { class: "input" });
    modal({
      title: "添加单个学生",
      body: h("div", {},
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", { class: "req" }, "姓名"), name),
          h("div", { class: "field" }, h("label", { class: "req" }, "学校"), school)),
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", { class: "req" }, "年级"), grade),
          h("div", { class: "field" }, h("label", {}, "组别（可选）"), group)),
        h("div", { class: "field" }, h("label", {}, "指导教师"), teacher)),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          try {
            const res = await api.post("/api/admin/students", {
              name: name.value.trim(), school: school.value.trim(), grade: grade.value.trim(),
              group: group.value.trim(), teacher_name: teacher.value.trim(),
            });
            close();
            showPasswordModal(`创建成功 · ${res.entry_no}`, res.entry_no, res.initial_password);
            load();
          } catch (e) { toastErr(e.message); }
        } }, "创建"),
      ],
    });
  }

  function showImport() {
    const fileInput = h("input", { type: "file", accept: ".csv", style: "display:none",
      onchange: async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        const fd = new FormData(); fd.append("file", f);
        const box2 = h("div", { class: "text-c muted" }, "导入中…");
        resultBox.innerHTML = ""; resultBox.append(box2);
        try {
          const res = await api.upload("/api/admin/students/import", fd);
          drawImportResult(res);
        } catch (err) { resultBox.innerHTML = ""; resultBox.append(h("p", { style: "color:var(--danger)" }, err.message)); }
      } });
    const resultBox = h("div", { class: "mt16" });
    modal({
      title: "批量导入学生（CSV）",
      wide: true,
      body: h("div", {},
        h("p", { class: "small muted" },
          "CSV 列：姓名、学校、年级、组别（可选，仅三年级选报高段组时填）、指导教师、作品名称（可选）。系统自动生成参赛编号与随机初始密码，学生首登强制改密。"),
        h("button", { class: "btn btn-ghost btn-sm", onclick: () => download("/static/templates/学生导入模板.csv") }, "⬇️ 下载导入模板"),
        h("div", { class: "dropzone mt16", style: "padding:18px", onclick: () => fileInput.click() },
          h("p", {}, "点击选择 CSV 文件"), fileInput),
        resultBox),
      actions: (close) => [h("button", { class: "btn", onclick: close }, "完成")],
    });
  }

  function drawImportResult(res) {
    const box = h("div", {});
    if (res.created > 0) {
      box.append(h("div", { class: "row mb8" },
        badge(`成功导入 ${res.created} 人`, "ok"),
        h("button", { class: "btn btn-sm btn-ok", onclick: () => downloadAccounts(res.accounts_csv) }, "⬇️ 下载账号单（含初始密码）")));
      box.append(h("p", { class: "small", style: "color:var(--warn)" },
        "⚠️ 账号单仅此一次展示机会，请立即下载并分发给学校（初始密码不存储在系统中）。"));
    }
    if (res.errors?.length) {
      box.append(h("div", { class: "sub-card mt8" },
        h("strong", {}, `失败 ${res.errors.length} 条：`),
        ...res.errors.slice(0, 30).map((e) => h("div", { class: "small", style: "color:var(--danger)" }, e))));
    }
    const rb = $("#modal-root .modal .mt16");
    if (rb) { rb.innerHTML = ""; rb.append(box); }
    else modal({ title: "导入结果", body: box, actions: (c) => [h("button", { class: "btn", onclick: c }, "关闭")] });
  }

  function downloadAccounts(csv) {
    const blob = new Blob(["\ufeff" + csv], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "账号单.csv";
    a.click();
  }
}

function showPasswordModal(title, entryNo, pwd) {
  modal({
    title,
    body: h("div", { class: "text-c" },
      h("div", { class: "sub-card", style: "display:inline-block;text-align:left;min-width:300px" },
        h("div", { class: "kv" },
          h("div", { class: "k" }, "参赛编号"), h("div", { style: "font-weight:700" }, entryNo),
          h("div", { class: "k" }, "初始密码"), h("div", { style: "font-weight:700;font-size:20px;color:var(--primary)" }, pwd))),
      h("p", { class: "small muted mt8" }, "密码已加密存储，本窗口关闭后无法再次查看，请立即复制保存。")),
    actions: (close) => [
      h("button", { class: "btn btn-ghost", onclick: () => copyText(pwd) }, "复制"),
      h("button", { class: "btn", onclick: close }, "我已保存"),
    ],
  });
}

/* ================= 题库管理 ================= */
async function tabQuestions(el) {
  let group = "high";
  const bar = h("div", { class: "filter-bar" },
    h("button", { class: "btn btn-sm", id: "btn-high", onclick: () => switchGroup("high") }, "小学高段组"),
    h("span", { style: "flex:1" }),
    h("button", { class: "btn btn-ok btn-sm", onclick: () => showAIGen() }, "🤖 AI 生成题目"),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => showQImport() }, "📥 批量导入"),
    h("button", { class: "btn btn-sm", onclick: () => showQEdit(null) }, "＋ 新增题目"));
  const listBox = h("div", {});
  el.append(bar, listBox);

  /* ---- AI 智能出题：调用已配置的 LLM，按老师要求生成题目，预览确认后导入 ---- */
  function showAIGen() {
    const topic = h("textarea", { class: "textarea", rows: 3,
      placeholder: "用一句话告诉 AI 出什么题，如：\n围绕产生式表示法（IF-THEN 规则）与正向推理，结合智能垃圾分类站场景出题" });
    topic.value = "围绕词元推理核心概念（框架表示法、产生式表示法、演绎与归纳推理），结合生活场景出题";
    const scene = h("input", { class: "input", placeholder: "可选，如：图书馆借阅 / 外卖订单 / 物流快递" });
    const count = h("input", { class: "input", type: "number", min: 1, max: 20, value: 5 });
    const qtype = dropdown({ options: [{ v: "mix", t: "混合（单选+多选+判断）" }, { v: "single", t: "仅单选题" },
      { v: "multiple", t: "仅多选题" }, { v: "judge", t: "仅判断题" }] });
    const genBtn = h("button", { class: "btn", onclick: doGen }, "🤖 生成");
    const area = h("div", { class: "mt16" });

    async function doGen() {
      if (!topic.value.trim()) { toastErr("请先填写知识点范围 / 老师要求"); return; }
      genBtn.disabled = true;
      genBtn.textContent = "生成中…（约需十几秒）";
      area.innerHTML = "";
      try {
        const r = await api.post("/api/admin/questions/ai-generate", {
          topic: topic.value.trim(), scene: scene.value.trim(),
          count: parseInt(count.value) || 5, qtype: qtype.getValue(),
        });
        drawPreview(r.items, r.errors);
      } catch (e) { area.innerHTML = ""; toastErr(e.message); }
      genBtn.disabled = false;
      genBtn.textContent = "🤖 生成";
    }

    function drawPreview(items, errors) {
      if (!items.length) { area.append(empty("没有可用的题目：" + (errors || []).join("；"))); return; }
      area.innerHTML = "";
      const checks = [];
      const listBox = h("div", { class: "sub-card", style: "max-height:320px;overflow-y:auto" });
      for (const [i, it] of items.entries()) {
        const cb = h("input", { type: "checkbox", checked: true });
        checks.push({ cb, it });
        listBox.append(h("div", { class: "row", style: "align-items:flex-start;border-bottom:1px dashed var(--line);padding:8px 4px" },
          cb,
          h("div", { style: "flex:1" },
            h("div", {}, badge({ single: "单选", multiple: "多选", judge: "判断" }[it.type], "info"),
              " ", `${it.score} 分 · ${it.topic || "—"}`),
            h("div", { class: "small mt8", style: "font-weight:600" }, it.stem),
            h("div", { class: "small muted" },
              "选项：" + (it.options.map((o) => o.key + "." + o.text).join("　") || "（判断题）"),
              " ｜ 答案：" + it.answer.join(",")))));
      }
      const errBox = (errors || []).length
        ? h("div", { class: "small", style: "color:var(--warn)" }, "部分条目已剔除：" + errors.join("；"))
        : "";
      area.append(
        h("div", { class: "spread mb8" },
          h("strong", {}, `✨ AI 生成了 ${items.length} 道题（勾选后导入）`),
          h("div", { class: "row" },
            h("button", { class: "btn btn-ghost btn-sm", onclick: () => checks.forEach((x) => x.cb.checked = true) }, "全选"),
            h("button", { class: "btn btn-ghost btn-sm", onclick: () => checks.forEach((x) => x.cb.checked = false) }, "清空"),
            h("button", { class: "btn btn-ok", onclick: doImport }, "📥 导入所选"))),
        errBox, listBox);

      async function doImport() {
        const chosen = checks.filter((x) => x.cb.checked).map((x) => x.it);
        if (!chosen.length) { toastErr("请至少勾选一道题"); return; }
        try {
          const r = await api.post("/api/admin/questions/import", { group_code: group, items: chosen });
          toastOk(`已导入 ${r.added} 道题` + (r.errors.length ? `，失败 ${r.errors.length} 条` : ""));
          if (r.errors.length) console.warn(r.errors);
          load();
        } catch (e) { toastErr(e.message); }
      }
    }

    modal({
      title: "🤖 AI 智能出题（调用智能体设置中的大模型）",
      wide: true,
      body: h("div", {},
        h("div", { class: "callout mb16" },
          "AI 按你的要求自动命题并自检格式，生成后可勾选、剔除再入库；建议先小批量试生成，确认风格后再批量。"),
        h("div", { class: "field" }, h("label", { class: "req" }, "老师要求（知识点范围）"), topic),
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", {}, "生活场景（可选）"), scene),
          h("div", { class: "form-row" },
            h("div", { class: "field" }, h("label", {}, "题量（1—20）"), count),
            h("div", { class: "field" }, h("label", {}, "题型"), qtype))),
        h("div", { class: "row" }, genBtn),
        area),
      actions: (close) => [h("button", { class: "btn btn-ghost", onclick: close }, "关闭")],
    });
  }

  async function switchGroup(g) {
    group = g;
    const bh = $("#btn-high", el);
    if (bh) bh.className = "btn btn-sm" + (g === "high" ? "" : " btn-ghost");
    load();
  }

  async function load() {
    listBox.innerHTML = "";
    const data = await api.get(`/api/admin/questions?group=${group}`);
    if (!data.items.length) { listBox.append(empty("暂无题目，点击「新增题目」或「批量导入」")); return; }
    listBox.append(h("div", { class: "tablewrap" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ..."ID 题型 知识点 题干 分值 状态 操作".split(" ").map((c) => h("th", {}, c)))),
      h("tbody", {}, ...data.items.map((r) => h("tr", {},
        h("td", { class: "muted" }, String(r.id)),
        h("td", { class: "nowrap" }, { single: "单选", multiple: "多选", judge: "判断" }[r.type]),
        h("td", { class: "nowrap" }, r.topic || "—"),
        h("td", { style: "max-width:420px" }, r.stem.slice(0, 60) + (r.stem.length > 60 ? "…" : "")),
        h("td", { class: "num" }, String(r.score)),
        h("td", {}, badge(r.enabled ? "启用" : "停用", r.enabled ? "ok" : "off")),
        h("td", { class: "nowrap" },
          h("button", { class: "btn btn-ghost btn-sm", onclick: () => showQEdit(r) }, "编辑"),
          h("button", { class: "btn btn-ghost btn-sm", style: "color:var(--danger)", onclick: () => {
            confirmBox("确定删除该题目？", async () => { await api.del(`/api/admin/questions/${r.id}`); load(); }, { danger: true, yes: "删除" });
          } }, "删除"))))))));
  }

  function showQEdit(q) {
    const type = dropdown({ options: [{ v: "single", t: "单选题" }, { v: "multiple", t: "多选题" }, { v: "judge", t: "判断题" }], value: q?.type || "single" });
    const topic = h("input", { class: "input", value: q?.topic || "", placeholder: "知识点标签（如：框架表示法）" });
    const stem = h("textarea", { class: "textarea", rows: 3 }, q?.stem || "");
    const score = h("input", { class: "input", type: "number", min: 0.5, step: 0.5, value: q?.score ?? 1 });
    const optsWrap = h("div", {});
    const ansInput = h("input", { class: "input", placeholder: q?.type === "judge" ? "A=正确 / B=错误" : "答案，多选用逗号分隔，如 A,C" });
    ansInput.value = q ? q.answer.join(",") : "";

    function renderOpts() {
      optsWrap.innerHTML = "";
      if (type.getValue() === "judge") {
        optsWrap.append(h("p", { class: "small muted" }, "判断题选项固定为：A=正确，B=错误。"));
        return;
      }
      const n = 4;
      for (let i = 0; i < n; i++) {
        const key = "ABCD"[i];
        const val = h("input", { class: "input", value: q?.options?.find((o) => o.key === key)?.text || "", placeholder: `选项 ${key}（留空则不启用）` });
        val.dataset.key = key;
        optsWrap.append(h("div", { class: "row mb8", style: "gap:8px" },
          h("span", { style: "font-weight:700;width:18px" }, key), val));
      }
    }
    type.querySelector(".dropdown-btn").addEventListener("click", renderOpts);
    renderOpts();

    modal({
      title: q ? `编辑题目 #${q.id}` : "新增题目",
      wide: true,
      body: h("div", {},
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", {}, "题型"), type),
          h("div", { class: "field" }, h("label", {}, "知识点"), topic)),
        h("div", { class: "field" }, h("label", { class: "req" }, "题干"), stem),
        h("div", { class: "field" }, h("label", {}, "选项"), optsWrap),
        h("div", { class: "form-row" },
          h("div", { class: "field" }, h("label", { class: "req" }, "答案"), ansInput),
          h("div", { class: "field" }, h("label", {}, "分值"), score))),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          const options = type.getValue() === "judge"
            ? [{ key: "A", text: "正确" }, { key: "B", text: "错误" }]
            : $$("input[data-key]", optsWrap).map((i) => ({ key: i.dataset.key, text: i.value.trim() })).filter((o) => o.text);
          const body = {
            group_code: group, type: type.getValue(), stem: stem.value.trim(),
            options, answer: ansInput.value.split(/[,，]/).map((s) => s.trim().toUpperCase()).filter(Boolean),
            score: parseFloat(score.value) || 1, topic: topic.value.trim(), enabled: true,
          };
          try {
            if (q) await api.put(`/api/admin/questions/${q.id}`, body);
            else await api.post("/api/admin/questions", body);
            toastOk("已保存"); close(); load();
          } catch (e) { toastErr(e.message); }
        } }, "保存"),
      ],
    });
  }

  function showQImport() {
    const text = h("textarea", { class: "textarea", rows: 10, placeholder:
      "粘贴 JSON 数组，每条：{\"type\":\"single\",\"stem\":\"题干\",\"options\":[{\"key\":\"A\",\"text\":\"…\"},…],\"answer\":[\"A\"],\"score\":2,\"topic\":\"…\"}" });
    modal({
      title: "批量导入题目（JSON）",
      wide: true,
      body: h("div", {},
        h("p", { class: "small muted" }, "导入到当前组别，可先粘贴 JSON 数组后导入。判断题可不填选项。"),
        text),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          try {
            const items = JSON.parse(text.value);
            const r = await api.post("/api/admin/questions/import", { group_code: group, items });
            toastOk(`导入 ${r.added} 题` + (r.errors.length ? `，失败 ${r.errors.length} 条（详见控制台）` : ""));
            if (r.errors.length) console.warn(r.errors);
            close(); load();
          } catch (e) { toastErr(e.message); }
        } }, "导入"),
      ],
    });
  }

  await switchGroup(group);
}

/* ================= 赛事设置 ================= */
async function tabSettings(el) {
  const s = await api.get("/api/admin/settings");
  el.append(h("h2", { style: "margin-bottom:14px" }, "赛事设置"));

  /* 提交设置 */
  const subOpen = h("input", { type: "checkbox", checked: s.submission.open, style: "display:none" });
  const subDeadline = h("input", { class: "input", type: "datetime-local", value: (s.submission.deadline || "").slice(0, 16) });
  const subRetract = h("input", { type: "checkbox", checked: !!s.submission.allow_retract, style: "display:none" });
  el.append(h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "作品提交通道（本届仅开放小学高段组，此通道未启用）")),
    h("div", { class: "row mb16" },
      h("label", { class: "row", style: "gap:8px" }, h("span", { class: "switch" }, subOpen, h("span", { class: "slider" })), h("span", { class: "small" }, "开放提交通道")),
      h("label", { class: "row", style: "gap:8px" }, h("span", { class: "switch" }, subRetract, h("span", { class: "slider" })), h("span", { class: "small" }, "允许截止前撤回重交"))),
    h("div", { class: "field", style: "max-width:320px" }, h("label", {}, "提交截止时间（留空不限制）"), subDeadline),
  ));

  /* 考试设置 */
  const examBoxes = {};
  el.append(h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "线上答题考试安排（高段 / 中学）")),
    h("div", { class: "exam-cfg-grid" },
      ...["high"].map((g) => {
        const c = s.exams[g] || {};
        const enabled = h("input", { type: "checkbox", checked: !!c.enabled, style: "display:none" });
        const startAt = h("input", { class: "input", type: "datetime-local", value: (c.start_at || "").slice(0, 16) });
        const endAt = h("input", { class: "input", type: "datetime-local", value: (c.end_at || "").slice(0, 16) });
        const dur = h("input", { class: "input", type: "number", min: 5, max: 240, value: c.duration_minutes ?? 40 });
        const showScore = h("input", { type: "checkbox", checked: c.show_score_after !== false, style: "display:none" });
        const allowRe = h("input", { type: "checkbox", checked: c.allow_resubmit !== false, style: "display:none" });
        examBoxes[g] = { enabled, startAt, endAt, dur, showScore, allowRe };
        return h("div", { class: "sub-card" },
          h("div", { class: "spread mb8" },
            h("strong", {}, GROUP_NAMES[g]),
            h("label", { class: "row", style: "gap:6px" }, h("span", { class: "switch" }, enabled, h("span", { class: "slider" })), h("span", { class: "small muted" }, "启用"))),
          h("div", { class: "field" }, h("label", { class: "small" }, "开始时间"), startAt),
          h("div", { class: "field" }, h("label", { class: "small" }, "结束时间（进入作答的截止时刻）"), endAt),
          h("div", { class: "field" }, h("label", { class: "small" }, "作答时长（分钟）"), dur),
          h("div", { class: "row" },
            h("label", { class: "row", style: "gap:6px" }, h("span", { class: "switch" }, showScore, h("span", { class: "slider" })), h("span", { class: "small" }, "交卷后立即显示得分")),
            h("label", { class: "row", style: "gap:6px" }, h("span", { class: "switch" }, allowRe, h("span", { class: "slider" })), h("span", { class: "small" }, "允许截止前恢复作答再提交"))));
      }))));

  /* 公示与晋级 */
  const pubBoxes = {};
  const maskNames = h("input", { type: "checkbox", checked: s.publish.mask_names !== false, style: "display:none" });
  el.append(h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "成绩公示与晋级")),
    h("div", { class: "row mb16", style: "gap:24px" },
      ...["high"].map((g) => {
        const on = h("input", { type: "checkbox", checked: !!s.publish[g], style: "display:none" });
        pubBoxes[g] = on;
        return h("label", { class: "row", style: "gap:6px" },
          h("span", { class: "switch" }, on, h("span", { class: "slider" })),
          h("span", { class: "small" }, `公示${GROUP_NAMES[g]}成绩`));
      }),
      h("label", { class: "row", style: "gap:6px" }, h("span", { class: "switch" }, maskNames, h("span", { class: "slider" })), h("span", { class: "small" }, "公示名单姓名脱敏"))),
    h("div", { class: "form-row" },
      ...["high"].map((g) => {
        const q = h("input", { class: "input", type: "number", min: 0, value: (s.quota || {})[g] ?? 0 });
        pubBoxes[g + "_quota"] = q;
        return h("div", { class: "field" }, h("label", { class: "small" }, `${GROUP_NAMES[g]} · 晋级名额（0 = 不设）`), q);
      }))));

  el.append(h("button", { class: "btn btn-lg", onclick: saveAll }, "保存全部设置"));

  async function saveAll() {
    const dt = (v) => v ? v.replace("T", " ") + (v.length === 16 ? ":00" : "") : "";
    try {
      await api.put("/api/admin/settings", {
        submission: { open: subOpen.checked, allow_retract: subRetract.checked, deadline: dt(subDeadline.value) || null },
        exams: Object.fromEntries(["high"].map((g) => [g, {
          enabled: examBoxes[g].enabled.checked,
          start_at: dt(examBoxes[g].startAt.value),
          end_at: dt(examBoxes[g].endAt.value),
          duration_minutes: parseInt(examBoxes[g].dur.value) || 40,
          show_score_after: examBoxes[g].showScore.checked,
          allow_resubmit: examBoxes[g].allowRe.checked,
        }])),
        publish: { high: pubBoxes.high.checked, mask_names: maskNames.checked },
        quota: { high: parseInt(pubBoxes["high_quota"].value) || 0 },
      });
      toastOk("设置已保存");
    } catch (e) { toastErr(e.message); }
  }
}

/* ================= 成绩与公示 ================= */
async function tabScores(el) {
  let group = "high";
  const listBox = h("div", {});
  const bar = h("div", { class: "filter-bar" },
    ...["high"].map((g) =>
      h("button", { class: "btn btn-sm btn-ghost", id: `rk-${g}`, onclick: () => switchG(g) }, GROUP_NAMES[g])),
    h("span", { style: "flex:1" }),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => download(`/api/admin/ranking/export?group=${group}`) }, "⬇️ 导出排名 CSV"));
  el.append(bar, listBox);

  async function switchG(g) {
    group = g;
    ["high"].forEach((k) => $("#rk-" + k, el).className = "btn btn-sm" + (k === g ? "" : " btn-ghost"));
    load();
  }

  async function load() {
    listBox.innerHTML = "";
    const data = await api.get(`/api/admin/ranking?group=${group}`);
    listBox.append(h("div", { class: "row mb16" },
      badge(`已参评 ${data.items.length} / 已提交 ${data.submitted}`, "info"),
      h("span", { class: "small muted" }, `晋级名额：${data.quota || "未设置（在赛事设置中配置）"}`)));
    if (!data.items.length) { listBox.append(empty("尚无已交卷的选手")); return; }
    listBox.append(h("div", { class: "tablewrap" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {},
        ..."名次 参赛编号 姓名 学校 年级 知识测试得分 用时 答题数 切屏 实操得分 合并总分 晋级".split(" ").map((c) => h("th", {}, c)))),
      h("tbody", {}, ...data.items.map((r) => h("tr", {},
        h("td", { class: `num ${r.rank <= 3 ? "rank-top" : ""}` }, String(r.rank)),
        h("td", { class: "nowrap" }, r.entry_no),
        h("td", { class: "nowrap" }, r.name),
        h("td", {}, r.school),
        h("td", { class: "nowrap" }, r.grade || "—"),
        h("td", { class: "num" }, String(r.score)),
        h("td", { class: "num" }, fmtDur(r.duration_seconds)),
        h("td", { class: "num" }, String(r.answered ?? "—")),
        h("td", { class: "num" }, r.suspicious_events ? h("span", { class: "badge badge-warn" }, String(r.suspicious_events)) : "0"),
        h("td", { class: "num" }, r.agent_score != null ? String(r.agent_score) : "—"),
        h("td", { class: "num rank-top" }, r.merged != null ? String(r.merged) : "—"),
        h("td", {}, r.promoted ? badge("晋级", "ok") : "")))),
        h("td", {}, r.promoted ? badge("晋级", "ok") : "")))))));
  }

  await switchG(group);
}

/* ================= 评委管理 ================= */
async function tabJudges(el) {
  // 评委系统已下线（本届评审由组委会教师线下开展），仅保留直达时的说明页
  el.append(h("div", { class: "card lock-screen", style: "max-width:560px;margin:30px auto" },
    h("div", { style: "font-size:44px" }, "🧑‍⚖️"),
    h("h3", {}, "评委系统未启用"),
    h("p", { class: "muted" },
      "本届评审由组委会教师线下开展：智能体作品检测与结论请在「🗂️ 智能体任务」中完成，知识测试成绩由系统自动判分。"),
  ));
}

async function tabAnnouncements(el) {
  const data = await api.get("/api/admin/announcements");
  el.append(h("div", { class: "spread mb16" },
    h("h2", { style: "margin:0" }, "公告管理"),
    h("button", { class: "btn btn-sm", onclick: () => showEdit(null) }, "＋ 新增公告")));
  if (!data.items.length) { el.append(empty("暂无公告")); return; }
  el.append(h("div", { class: "tablewrap" }, h("table", { class: "tbl" },
    h("thead", {}, h("tr", {}, ..."标题 内容 置顶 发布时间 操作".split(" ").map((c) => h("th", {}, c)))),
    h("tbody", {}, ...data.items.map((r) => h("tr", {},
      h("td", { class: "nowrap" }, r.pinned ? h("span", { class: "badge badge-danger", style: "margin-right:5px" }, "置顶") : "", r.title),
      h("td", { style: "max-width:400px" }, r.body.slice(0, 80) + (r.body.length > 80 ? "…" : "")),
      h("td", {}, r.pinned ? "是" : "—"),
      h("td", { class: "nowrap" }, fmtTime(r.created_at)),
      h("td", { class: "nowrap" },
        h("button", { class: "btn btn-ghost btn-sm", onclick: () => showEdit(r) }, "编辑"),
        h("button", { class: "btn btn-ghost btn-sm", style: "color:var(--danger)", onclick: () => {
          confirmBox("删除该公告？", async () => { await api.del(`/api/admin/announcements/${r.id}`); loadTab($("#app").lastElementChild); }, { danger: true, yes: "删除" });
        } }, "删除"))))))));

  function showEdit(a) {
    const title = h("input", { class: "input", value: a?.title || "" });
    const body = h("textarea", { class: "textarea", rows: 5 }, a?.body || "");
    const pin = h("input", { type: "checkbox", checked: !!a?.pinned });
    modal({
      title: a ? "编辑公告" : "新增公告",
      body: h("div", {},
        h("div", { class: "field" }, h("label", { class: "req" }, "标题"), title),
        h("div", { class: "field" }, h("label", { class: "req" }, "内容"), body),
        h("label", { class: "row", style: "gap:6px" }, pin, " 置顶显示")),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          const payload = { title: title.value.trim(), body: body.value.trim(), pinned: pin.checked };
          try {
            if (a) await api.put(`/api/admin/announcements/${a.id}`, payload);
            else await api.post("/api/admin/announcements", payload);
            toastOk("已保存"); close(); loadTab($("#app").lastElementChild);
          } catch (e) { toastErr(e.message); }
        } }, "保存"),
      ],
    });
  }
}

/* ================= 审计日志 ================= */
async function tabLogs(el, page = 1) {
  const data = await api.get(`/api/admin/logs?page=${page}&size=60`);
  el.append(h("h2", { style: "margin-bottom:14px" }, "审计日志"),
    h("p", { class: "small muted mb16" }, "记录登录、提交、评分、考试异常事件等关键操作，供组委会追溯。"));
  const box = h("div", { class: "card" });
  for (const r of data.items) {
    box.append(h("div", { class: "logline" },
      `${r.ts}  ${r.actor || "-"}  ${r.action}  ${r.detail || ""}  [${r.ip || "-"}]`));
  }
  if (!data.items.length) box.append(empty("暂无日志"));
  el.append(box);
  const pages = Math.max(1, Math.ceil(data.total / 60));
  el.append(h("div", { class: "pager" },
    h("button", { class: "btn btn-ghost btn-sm", disabled: page <= 1, onclick: () => { el.innerHTML = ""; tabLogs(el, page - 1); } }, "上一页"),
    h("span", {}, `${page} / ${pages}`),
    h("button", { class: "btn btn-ghost btn-sm", disabled: page >= pages, onclick: () => { el.innerHTML = ""; tabLogs(el, page + 1); } }, "下一页")));
}

/* ================= 智能体设置（题目要求 + LLM 配置） ================= */
const LLM_PRESETS = [
  { name: "SiliconFlow 硅基流动", base: "https://api.siliconflow.cn/v1", models: "如 Qwen/Qwen2.5-7B-Instruct、deepseek-ai/DeepSeek-V3" },
  { name: "智谱 GLM", base: "https://open.bigmodel.cn/api/paas/v4", models: "如 glm-4-flash、glm-4-air" },
  { name: "DeepSeek", base: "https://api.deepseek.com/v1", models: "如 deepseek-chat" },
  { name: "通义千问", base: "https://dashscope.aliyuncs.com/compatible-mode/v1", models: "如 qwen-plus、qwen-turbo" },
  { name: "自定义（OpenAI 兼容）", base: "", models: "填写服务商提供的模型名" },
];

async function tabAgent(el) {
  const [settings, llmData] = await Promise.all([
    api.get("/api/admin/settings"),
    api.get("/api/admin/llm"),
  ]);
  el.append(h("h2", { style: "margin-bottom:14px" }, "智能体设置"));

  /* ---- 题目要求 ---- */
  const tTitle = h("input", { class: "input", value: settings.task?.title || "", placeholder: "标题，如：设计智能体 · 题目要求" });
  const tContent = h("textarea", { class: "textarea", rows: 12, placeholder: "题目要求正文（支持换行）…" });
  tContent.value = settings.task?.content || "";
  el.append(h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "📋 题目要求"), badge("学生端「设计智能体」首页展示", "info")),
    h("div", { class: "field" }, h("label", {}, "标题"), tTitle),
    h("div", { class: "field" }, h("label", {}, "正文"), tContent),
    h("div", { class: "row", style: "justify-content:flex-end" },
      h("button", { class: "btn", onclick: async () => {
        try {
          await api.put("/api/admin/task", { title: tTitle.value.trim(), content: tContent.value.trim() });
          toastOk("题目要求已保存");
        } catch (e) { toastErr(e.message); }
      } }, "保存题目要求"))));

  /* ---- LLM 配置 ---- */
  const llm = llmData.llm;
  const enabled = h("input", { type: "checkbox", checked: !!llm.enabled, style: "display:none" });
  const providerSel = dropdown({
    options: LLM_PRESETS.map((p) => ({ v: p.name, t: p.name })),
    value: llm.provider || LLM_PRESETS[0].name,
    onChange: (v) => {
      const p = LLM_PRESETS.find((x) => x.name === v);
      if (p && p.base) baseInput.value = p.base;
      modelInput.placeholder = p ? p.models : "";
    },
  });
  const baseInput = h("input", { class: "input", value: llm.api_base || "",
    placeholder: "支持粘贴任意形式：…/v1、完整请求地址、无 /v1 的地址，自动识别" });
  // 实时归一化提示：无论粘贴哪种形式（Base URL / 完整 chat/completions / messages / 无 /v1），都路由到正确端点
  const baseHint = h("div", { class: "small mt8" });
  function normBase(raw) {
    let u = (raw || "").trim().replace(/\/+$/, "");
    for (const sfx of ["/chat/completions", "/messages"]) {
      if (u.toLowerCase().endsWith(sfx)) { u = u.slice(0, -sfx.length).replace(/\/+$/, ""); break; }
    }
    if (u && !u.toLowerCase().endsWith("/v1")) u += "/v1";
    return u;
  }
  function updateBaseHint() {
    const v = baseInput.value.trim();
    if (!v) { baseHint.textContent = ""; return; }
    const u = normBase(v);
    const ok = /^https?:\/\//.test(u);
    baseHint.style.color = ok ? "var(--ok)" : "var(--danger)";
    baseHint.textContent = (ok ? "✓ 系统将请求：" : "✗ 地址需以 http(s):// 开头 → ") + u + "/chat/completions";
  }
  baseInput.addEventListener("input", updateBaseHint);
  const keyInput = h("input", { class: "input", type: "password", placeholder: llm.api_key_set
    ? `已配置（${llm.api_key_masked}），留空表示不修改` : "sk-…", autocomplete: "new-password" });
  const modelInput = h("input", { class: "input", value: llm.model || "", placeholder: "如 Qwen/Qwen2.5-7B-Instruct" });
  const tempInput = h("input", { class: "input", type: "number", min: 0, max: 2, step: 0.1, value: llm.temperature ?? 0.7 });
  const maxTokInput = h("input", { class: "input", type: "number", min: 100, max: 8000, step: 100, value: llm.max_tokens ?? 800 });
  const prefixInput = h("textarea", { class: "textarea", rows: 3, placeholder: "（可选）加在所有智能体系统提示词最前面的统一要求，如：请始终使用简体中文…" });
  prefixInput.value = llm.system_prefix || "";
  updateBaseHint();

  const testResult = h("div", { class: "small mt8" });
  el.append(h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "🧠 大模型（LLM）配置"),
      h("label", { class: "row", style: "gap:6px" },
        h("span", { class: "switch" }, enabled, h("span", { class: "slider" })),
        h("span", { class: "small" }, "启用学生对话"))),
    h("div", { class: "callout mb16" },
      "学生保存设计后，可与自己的智能体进行文字对话。对话走 OpenAI 兼容接口（/chat/completions）。"
      + "API Key 加密保存在服务器，不会展示给学生；若 Key 无效或未开放权限，学生与老师都会收到补全配置的提醒。"),
    h("div", { class: "form-row" },
      h("div", { class: "field" }, h("label", {}, "服务商预设"), providerSel),
      h("div", { class: "field" }, h("label", { class: "req" }, "接口地址（Base URL，支持任意形式自动识别）"), baseInput, baseHint)),
    h("div", { class: "form-row" },
      h("div", { class: "field" }, h("label", { class: llm.api_key_set ? "" : "req" }, "API Key"), keyInput),
      h("div", { class: "field" }, h("label", { class: "req" }, "模型名称"), modelInput)),
    h("div", { class: "form-row" },
      h("div", { class: "field" }, h("label", {}, "温度 temperature（0—2，越大越发散）"), tempInput),
      h("div", { class: "field" }, h("label", {}, "单次回复上限 tokens"), maxTokInput)),
    h("div", { class: "field" }, h("label", {}, "统一系统提示词前缀（可选）"), prefixInput),
    h("div", { class: "row" },
      h("button", { class: "btn", onclick: saveLLM }, "保存配置"),
      h("button", { class: "btn btn-ghost", onclick: testLLM }, "🔌 测试连接"),
      testResult),
  ));

  async function saveLLM() {
    try {
      const r = await api.put("/api/admin/llm", {
        enabled: enabled.checked, provider: providerSel.getValue(), api_base: baseInput.value.trim(),
        api_key: keyInput.value.trim(), model: modelInput.value.trim(),
        temperature: parseFloat(tempInput.value) || 0.7, max_tokens: parseInt(maxTokInput.value) || 800,
        system_prefix: prefixInput.value.trim(),
      });
      toastOk("LLM 配置已保存");
      keyInput.value = "";
      keyInput.placeholder = `已配置（${r.llm.api_key_masked}），留空表示不修改`;
      testResult.innerHTML = "";
    } catch (e) { toastErr(e.message); }
  }

  async function testLLM() {
    // 只测试表单当前值，不落库；结果附带被测地址/模型/时间，避免误读旧结果
    testResult.textContent = "测试中…";
    testResult.style.color = "var(--muted)";
    try {
      const r = await api.post("/api/admin/llm/test", {
        api_base: baseInput.value.trim(), api_key: keyInput.value.trim(), model: modelInput.value.trim(),
        temperature: parseFloat(tempInput.value) || 0.7, max_tokens: parseInt(maxTokInput.value) || 800,
        system_prefix: prefixInput.value.trim(),
      });
      testResult.textContent = (r.ok ? "✅ " : "❌ ") + r.message;
      testResult.style.color = r.ok ? "var(--ok)" : "var(--danger)";
      if (r.ok) {
        // 测试成功 → 自动保存该配置（含启用开关），避免忘记点保存而丢失
        try {
          await api.put("/api/admin/llm", {
            enabled: enabled.checked, provider: providerSel.getValue(),
            api_base: baseInput.value.trim(), api_key: keyInput.value.trim(), model: modelInput.value.trim(),
            temperature: parseFloat(tempInput.value) || 0.7, max_tokens: parseInt(maxTokInput.value) || 800,
            system_prefix: prefixInput.value.trim(),
          });
          keyInput.value = "";
          keyInput.placeholder = "已保存，留空表示不修改";
          testResult.textContent += "（已自动保存）";
        } catch (e2) {
          testResult.textContent += "（⚠️ 自动保存失败：" + e2.message + "，请点「保存配置」）";
        }
      }
    } catch (e) {
      testResult.textContent = "❌ " + e.message;
      testResult.style.color = "var(--danger)";
    }
  }
}

/* ================= 智能体任务检测 ================= */
async function tabAgentTask(el) {
  let group = "", check = "";
  const agGroup = dropdown({ options: [{ v: "", t: "全部组别" }, ...Object.entries(GROUP_NAMES).map(([k, v]) => ({ v: k, t: v }))] });
  const agCheck = dropdown({ options: [{ v: "", t: "全部检测状态" }, { v: "none", t: "未开始" }, { v: "pending", t: "已提交待检测" }, { v: "ok", t: "合格" }, { v: "revise", t: "需修改" }] });
  agGroup.style.width = "150px";
  agCheck.style.width = "160px";
  const listBox = h("div", {});
  const bar = h("div", { class: "filter-bar" },
    agGroup,
    agCheck,
    h("button", { class: "btn btn-sm", onclick: load }, "查询"),
    h("span", { style: "flex:1" }),
    h("button", { class: "btn btn-ghost btn-sm", onclick: () => download("/api/admin/agents/export" + (group ? `?group=${group}` : "")) }, "⬇️ 导出 CSV"));
  el.append(bar, listBox);

  async function load() {
    group = agGroup.getValue();
    check = agCheck.getValue();
    listBox.innerHTML = "";
    const data = await api.get(`/api/admin/agents?group=${group}&check=${check}`);
    const items = data.items;
    const stat = {
      submitted: items.filter((x) => x.agent_status === "submitted").length,
      ok: items.filter((x) => x.check_status === "ok").length,
      revise: items.filter((x) => x.check_status === "revise").length,
      allOk: items.filter((x) => x.agent_status === "submitted" && x.auto.all_ok).length,
    };
    listBox.append(h("div", { class: "row mb16" },
      badge(`已提交 ${stat.submitted}`, "ok"),
      badge(`自动检测通过 ${stat.allOk}`, "info"),
      badge(`合格 ${stat.ok}`, "ok"),
      badge(`需修改 ${stat.revise}`, "warn"),
      h("span", { class: "small muted" }, `对话检测门槛：至少 ${data.min_rounds} 轮`)));
    if (!items.length) { listBox.append(empty("暂无数据")); return; }
    listBox.append(h("div", { class: "tablewrap" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ..."参赛编号 姓名 组别 智能体名称 任务状态 对话轮 自动检测 检测结论 操作".split(" ").map((c) => h("th", {}, c)))),
      h("tbody", {}, ...items.map((r) => h("tr", {},
        h("td", { class: "nowrap" }, r.entry_no),
        h("td", { class: "nowrap" }, r.name),
        h("td", { class: "nowrap" }, GROUP_NAMES[r.group_code]),
        h("td", {}, r.agent_name || "—"),
        h("td", {}, { none: badge("未开始", "off"), draft: badge("设计中", "info"),
                     saved: badge("已保存", "info"), submitted: badge("已提交", "ok") }[r.agent_status]),
        h("td", { class: "num" }, String(r.auto.chat_rounds)),
        h("td", {}, r.agent_status === "submitted"
          ? (r.auto.all_ok ? badge("通过", "ok") : badge("待关注", "warn"))
          : h("span", { class: "muted" }, "—")),
        h("td", {}, (r.agent_status !== "submitted" && r.check_status === "pending")
          ? h("span", { class: "muted" }, "—")
          : { pending: badge("待检测", "off"), ok: badge("合格", "ok"), revise: badge("需修改", "warn") }[r.check_status]),
        h("td", {}, h("div", { class: "row", style: "gap:5px" },
          h("button", { class: "btn btn-ghost btn-sm", onclick: () => showDetail(r) }, "检测"),
        ))))))));
  }

  async function loadQuiet() {
    const box = listBox;
    listBox.innerHTML = "";
    await load();
  }

  async function showDetail(r) {
    const d = await api.get(`/api/admin/agents/${r.student_id}`);
    const a = d.agent || {};
    const auto = r.auto;
    const chatList = h("div", { class: "chat-log", style: "height:300px" });
    if (!d.chats.length) chatList.append(h("div", { class: "text-c muted", style: "margin:auto" }, "尚无对话记录"));
    for (const m of d.chats) {
      chatList.append(h("div", { class: `chat-row ${m.role === "user" ? "me" : ""}` },
        h("div", { class: `chat-bubble ${m.role === "user" ? "user" : "ai"}` },
          h("div", { class: "small muted", style: "margin-bottom:3px" }, m.role === "user" ? "学生" : "智能体", m.created_at ? ` · ${m.created_at}` : ""),
          m.content)));
    }
    const checkSel = dropdown({ options: [{ v: "pending", t: "待检测" }, { v: "ok", t: "合格" }, { v: "revise", t: "需修改" }], value: r.check_status });
    const comment = h("textarea", { class: "textarea", rows: 2, placeholder: "检测备注（学生可见）" });
    comment.value = r.check_comment || "";

    modal({
      title: `智能体任务检测 · ${r.entry_no} ${r.name}`,
      wide: true,
      body: h("div", {},
        h("div", { class: "row mb16" },
          badge(`对话 ${r.auto.chat_rounds} 轮`, "info"),
          r.auto.design_ok ? badge("设计完整", "ok") : badge("设计不完整", "danger"),
          r.auto.chat_ok ? badge("对话达标", "ok") : badge(`对话不足 ${d.min_rounds} 轮`, "danger")),
        h("div", { class: "kv" },
          h("div", { class: "k" }, "智能体名称"), h("div", {}, a.name || "—"),
          h("div", { class: "k" }, "服务对象 / 场景"), h("div", {}, `${a.audience || "—"} · ${a.scenario || "—"}`),
          h("div", { class: "k" }, "角色定位"), h("div", { style: "white-space:pre-wrap" }, a.role || "—"),
          h("div", { class: "k" }, "便民问题"), h("div", { style: "white-space:pre-wrap" }, a.problem || "—"),
          h("div", { class: "k" }, "功能与技能"), h("div", { style: "white-space:pre-wrap" }, a.skills || "—"),
          h("div", { class: "k" }, "知识资料"), h("div", { style: "white-space:pre-wrap" }, a.knowledge || "—"),
          h("div", { class: "k" }, "语气 / 开场白"), h("div", {}, `${a.tone || "—"} · ${a.welcome || "—"}`)),
        h("div", { class: "card-title mt16" }, h("h3", {}, "对话记录")),
        chatList,
        h("div", { class: "form-row mt16" },
          h("div", { class: "field" }, h("label", {}, "检测结论"), checkSel),
          h("div", { class: "field" }, h("label", {}, "检测备注"), comment)),
      ),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          try {
            await api.put(`/api/admin/agents/${r.student_id}/check`,
              { check_status: checkSel.getValue(), check_comment: comment.value.trim() });
            toastOk("检测结论已保存");
            close(); loadQuiet();
          } catch (e) { toastErr(e.message); }
        } }, "保存结论"),
      ],
    });
  }

  await load();
}

/* ================= OJ 实操考试 ================= */
async function tabExam(el) {
  const [settings, questions, results] = await Promise.all([
    api.get("/api/admin/settings"),
    api.get("/api/admin/agent-exam/questions"),
    api.get("/api/admin/agent-exam/results"),
  ]);
  const exam = settings.agent_exam || {};

  /* ---- 开放设置与合并权重 ---- */
  const enabled = h("input", { type: "checkbox", checked: !!exam.enabled, style: "display:none" });
  const startAt = h("input", { class: "input", type: "datetime-local", value: (exam.start_at || "").slice(0, 16) });
  const endAt = h("input", { class: "input", type: "datetime-local", value: (exam.end_at || "").slice(0, 16) });
  const qw = h("input", { class: "input", type: "number", min: 0, max: 100, value: exam.quiz_weight ?? 50 });
  const aw = h("input", { class: "input", type: "number", min: 0, max: 100, value: exam.agent_weight ?? 50 });
  el.append(h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "⚙️ 实操考试设置"),
      h("label", { class: "row", style: "gap:6px" }, h("span", { class: "switch" }, enabled, h("span", { class: "slider" })),
        h("span", { class: "small" }, "开放实操考试"))),
    h("div", { class: "form-row" },
      h("div", { class: "field" }, h("label", { class: "small" }, "开始时间"), startAt),
      h("div", { class: "field" }, h("label", { class: "small" }, "结束时间"), endAt)),
    h("div", { class: "form-row" },
      h("div", { class: "field" }, h("label", { class: "small" }, "知识测试权重（%）"), qw),
      h("div", { class: "field" }, h("label", { class: "small" }, "实操考试权重（%）"), aw)),
    h("p", { class: "small muted" },
      "合并总分 = 知识测试得分/知识测试满分 × 知识测试权重 + 实操得分/实操满分 × 实操权重；两部分权重之和建议为 100。"),
    h("button", { class: "btn", onclick: async () => {
      const dt = (v) => v ? v.replace("T", " ") + (v.length === 16 ? ":00" : "") : "";
      try {
        await api.put("/api/admin/settings", { agent_exam: {
          enabled: enabled.checked, start_at: dt(startAt.value), end_at: dt(endAt.value),
          quiz_weight: parseFloat(qw.value) || 0, agent_weight: parseFloat(aw.value) || 0 } });
        toastOk("实操考试设置已保存");
      } catch (e) { toastErr(e.message); }
    } }, "保存设置")));

  /* ---- 考题管理 ---- */
  const qBox = h("div", {});
  const qCard = h("div", { class: "card mb16" },
    h("div", { class: "card-title" }, h("h3", {}, "📋 实操考题"),
      h("button", { class: "btn btn-sm", onclick: () => showQModal(null) }, "＋ 新增考题")),
    qBox);
  el.append(qCard);

  function drawQuestions() {
    qBox.innerHTML = "";
    if (!questions.items.length) { qBox.append(empty("暂无考题")); return; }
    for (const q of questions.items) {
      qBox.append(h("div", { class: "sub-card mb8" },
        h("div", { class: "spread" },
          h("div", {},
            h("strong", {}, q.title),
            h("span", { class: "badge badge-info", style: "margin-left:6px" }, `满分 ${q.total_score}`),
            h("span", { class: "badge " + (q.enabled ? "badge-ok" : "badge-off"), style: "margin-left:6px" },
              q.enabled ? "启用" : "停用")),
          h("div", { class: "row" },
            h("button", { class: "btn btn-ghost btn-sm", onclick: () => showQModal(q) }, "编辑"),
            h("button", { class: "btn btn-ghost btn-sm", style: "color:var(--danger)", onclick: () => {
              confirmBox(`删除考题「${q.title}」？`, async () => {
                await api.del(`/api/admin/agent-exam/questions/${q.id}`);
                toastOk("已删除");
                const i = questions.items.indexOf(q); if (i > -1) questions.items.splice(i, 1);
                drawQuestions();
              }, { danger: true, yes: "删除" });
            } }, "删除"))),
        h("div", { class: "small muted mt8", style: "white-space:pre-wrap" }, q.scene),
        h("div", { class: "small mt8", style: "white-space:pre-wrap" }, q.task_desc.slice(0, 120) + (q.task_desc.length > 120 ? "…" : "")),
        h("div", { class: "small muted mt8" }, `标准测试问题 ${q.test_questions.length} 道`)));
    }
  }
  drawQuestions();

  function showQModal(q) {
    const title = h("input", { class: "input", value: q?.title || "" });
    const scene = h("input", { class: "input", value: q?.scene || "", placeholder: "如：学校图书馆借阅服务台" });
    const desc = h("textarea", { class: "textarea", rows: 6, placeholder: "任务要求（含学生需录入的知识库材料）" });
    desc.value = q?.task_desc || "";
    const rowsWrap = h("div", {});
    const tqs = q ? q.test_questions.map((t) => ({ ...t })) : [];
    function drawRows() {
      rowsWrap.innerHTML = "";
      tqs.forEach((t, i) => {
        const qIn = h("input", { class: "input", value: t.q || "", placeholder: "标准测试问题" });
        const pIn = h("input", { class: "input", value: t.points || "", placeholder: "参考答案要点（判题依据，学生不可见）" });
        const sIn = h("input", { class: "input", type: "number", min: 1, value: t.score ?? 10, style: "width:90px" });
        qIn.addEventListener("input", () => tqs[i].q = qIn.value);
        pIn.addEventListener("input", () => tqs[i].points = pIn.value);
        sIn.addEventListener("input", () => tqs[i].score = parseFloat(sIn.value) || 0);
        rowsWrap.append(h("div", { class: "sub-card mb8" },
          h("div", { class: "spread mb8" },
            h("strong", { class: "small" }, `测试问题 ${i + 1}`),
            h("button", { class: "btn btn-ghost btn-sm", style: "color:var(--danger)", onclick: () => { tqs.splice(i, 1); drawRows(); } }, "删除")),
          h("div", { class: "field" }, h("label", { class: "small" }, "问题"), qIn),
          h("div", { class: "field" }, h("label", { class: "small" }, "参考答案要点（评分依据）"), pIn),
          h("div", { class: "field" }, h("label", { class: "small" }, "分值"), sIn)));
      });
    }
    drawRows();
    modal({
      title: q ? `编辑考题 · ${q.title}` : "新增实操考题",
      wide: true,
      body: h("div", {},
        h("div", { class: "field" }, h("label", { class: "req" }, "标题"), title),
        h("div", { class: "field" }, h("label", {}, "生活场景"), scene),
        h("div", { class: "field" }, h("label", { class: "req" }, "任务要求（含知识库材料）"), desc),
        h("div", { class: "spread mb8" }, h("strong", { class: "small" }, "标准测试问题（判题逐题运行）"),
          h("button", { class: "btn btn-ghost btn-sm", onclick: () => { tqs.push({ q: "", points: "", score: 10 }); drawRows(); } }, "＋ 添加问题")),
        rowsWrap),
      actions: (close) => [
        h("button", { class: "btn btn-ghost", onclick: close }, "取消"),
        h("button", { class: "btn", onclick: async () => {
          const payload = { title: title.value.trim(), scene: scene.value.trim(), task_desc: desc.value.trim(),
            test_questions: tqs.filter((t) => t.q.trim()), enabled: q ? q.enabled : true };
          try {
            if (q) await api.put(`/api/admin/agent-exam/questions/${q.id}`, payload);
            else await api.post("/api/admin/agent-exam/questions", payload);
            toastOk("已保存");
            close();
            const qs = await api.get("/api/admin/agent-exam/questions");
            questions.items = qs.items;
            drawQuestions();
          } catch (e) { toastErr(e.message); }
        } }, "保存"),
      ],
    });
  }

  /* ---- 判题记录 ---- */
  const rBox = h("div", {});
  el.append(h("div", { class: "card" },
    h("div", { class: "card-title" }, h("h3", {}, "🧾 判题记录"), badge(`实操满分 ${results.max_total}`, "info")),
    rBox));
  function drawResults() {
    rBox.innerHTML = "";
    if (!results.items.length) { rBox.append(empty("暂无学生")); return; }
    rBox.append(h("div", { class: "tablewrap" }, h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ..."参赛编号 姓名 任务状态 实操得分 判题时间 操作".split(" ").map((c) => h("th", {}, c)))),
      h("tbody", {}, ...results.items.map((r) => h("tr", {},
        h("td", { class: "nowrap" }, r.entry_no),
        h("td", { class: "nowrap" }, r.name),
        h("td", {}, { none: badge("未提交", "off"), running: badge("判题中", "warn"),
                     done: badge("已完成", "ok"), error: badge("失败", "danger") }[r.status || "none"]),
        h("td", { class: "num" }, r.score != null ? String(r.score) : "—"),
        h("td", { class: "nowrap" }, fmtTime(r.judged_at)),
        h("td", {}, h("div", { class: "row", style: "gap:5px" },
          r.status === "done" && h("button", { class: "btn btn-ghost btn-sm", onclick: () => showDetail(r) }, "详情"),
          r.status !== "running" && h("button", { class: "btn btn-ghost btn-sm", onclick: async () => {
            try { await api.post(`/api/admin/agent-exam/results/${r.student_id}/rejudge`); toastOk("已重新发起判题"); loadTab($("#app").lastElementChild); }
            catch (e) { toastErr(e.message); }
          } }, "重判")))))))));
  }
  drawResults();

  async function showDetail(r) {
    const d = await api.get(`/api/admin/agent-exam/results/${r.student_id}`);
    modal({
      title: `判题详情 · ${d.student.entry_no} ${d.student.name}`,
      wide: true,
      body: h("div", {},
        h("div", { class: "score-dims mb16" },
          h("div", { class: "score-dim" }, h("div", { class: "v" }, String(d.score ?? "—")), h("div", { class: "k" }, "实操得分")),
          h("div", { class: "score-dim" }, h("div", { class: "v" }, String(results.max_total)), h("div", { class: "k" }, "满分")),
          h("div", { class: "score-dim" }, h("div", { class: "v" }, fmtTime(d.judged_at)), h("div", { class: "k" }, "判题时间"))),
        ...d.detail.map((x) => h("div", { class: "sub-card mb8" },
          h("div", { class: "spread" },
            h("strong", { class: "small" }, x.q),
            h("span", { class: "badge " + (x.score >= x.max * 0.8 ? "badge-ok" : x.score > 0 ? "badge-warn" : "badge-danger") },
              `${x.score} / ${x.max}`)),
          h("div", { class: "small mt8", style: "white-space:pre-wrap" }, "智能体回答：" + x.agent_reply),
          h("div", { class: "small muted mt8" }, "评语：" + (x.comment || "—"))))),
      actions: (close) => [h("button", { class: "btn", onclick: close }, "关闭")],
    });
  }
}

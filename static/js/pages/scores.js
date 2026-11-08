/** 成绩公示页：按组别查看排名 / 凭参赛编号查询个人成绩。 */
import { api } from "../api.js?v=13";
import { h, $, $$, empty, fmtDur, toastErr } from "../ui.js?v=13";
import { setNav, GROUP_NAMES } from "../app.js?v=13";

export async function render(app) {
  setNav("成绩公示");
  app.innerHTML = "";

  const tabs = h("div", { class: "auth-tabs", style: "max-width:420px;margin:0 auto 18px" },
    ...Object.keys(GROUP_NAMES).map((g) =>
      h("button", { "data-g": g, onclick: () => load(g) }, GROUP_NAMES[g])));
  const wrap = h("div", { class: "card", style: "padding:26px" });
  app.append(
    h("div", { class: "text-c mb16" },
      h("h2", { style: "margin-bottom:6px" }, "初赛成绩公示"),
      h("p", { class: "muted small" }, "成绩由组委会统一发布，公示期内如对成绩有异议，请按规则向组委会反映。")),
    tabs, wrap,
  );

  async function load(group) {
    $$(".auth-tabs button", tabs).forEach((b) => b.classList.toggle("active", b.dataset.g === group));
    wrap.innerHTML = "";
    wrap.append(h("div", { class: "text-c muted", style: "padding:30px 0" }, "加载中…"));
    let data;
    try {
      data = await api.get(`/api/public/scores?group=${group}`);
    } catch (e) {
      wrap.innerHTML = "";
      wrap.append(h("div", { class: "lock-screen" },
        h("div", { style: "font-size:44px" }, "🔒"),
        h("p", { class: "muted" }, e.message)));
      return;
    }

    /* 个人查询 */
    wrap.innerHTML = "";
    const queryRow = h("div", { class: "row mb16", style: "justify-content:center" },
      h("input", { class: "input", id: "q-entry", placeholder: "输入参赛编号查询个人成绩（如 L0001）", style: "max-width:280px" }),
      h("button", { class: "btn btn-sm", onclick: doQuery }, "查询"),
    );
    const mineBox = h("div", { id: "mine-box" });
    wrap.append(h("p", { class: "text-c muted small" },
      `共 ${data.list.length} 名选手 · 前 ${data.quota || "—"} 名晋级省级决赛${data.mask ? "（姓名已脱敏）" : ""}`),
      queryRow, mineBox);

    async function doQuery() {
      const entry = $("#q-entry", wrap).value.trim();
      if (!entry) return;
      mineBox.innerHTML = "";
      try {
        const q = await api.get(`/api/public/scores?group=${group}&entry_no=${encodeURIComponent(entry)}`);
        const m = q.mine;
        mineBox.append(h("div", { class: "sub-card", style: "max-width:560px;margin:0 auto" },
          h("div", { class: "spread" },
            h("strong", {}, `${m.name} · ${m.entry_no}`),
            h("span", { class: "badge badge-ok" }, `第 ${m.rank} 名`)),
          h("p", { class: "small mt8" }, `得分 ${m.score} · 用时 ${fmtDur(m.duration_seconds)}`),
        ));
      } catch (e) {
        mineBox.append(h("p", { class: "small", style: "color:var(--danger);text-align:center" }, e.message));
      }
    }

    /* 排名表 */
    wrap.append(h("div", { class: "tablewrap mt16" }, buildTable(group, data.list)));
    if (!data.list.length) wrap.append(empty("该组别暂无公示成绩"));
  }

  function buildTable(group, list) {
    const thead = ["名次", "参赛编号", "姓名", "学校", "年级", "得分", "用时"];
    return h("table", { class: "tbl" },
      h("thead", {}, h("tr", {}, ...thead.map((c) => h("th", {}, c)))),
      h("tbody", {}, ...list.map((r, i) => h("tr", {},
        h("td", { class: `num ${r.rank <= 3 ? "rank-top" : ""}` }, String(r.rank)),
        h("td", { class: "nowrap" }, r.entry_no),
        h("td", { class: "nowrap" }, r.name),
        h("td", {}, r.school),
        h("td", { class: "nowrap" }, r.grade || "—"),
        h("td", { class: "num rank-top" }, String(r.score)),
        h("td", { class: "num" }, fmtDur(r.duration_seconds)),
      ))));
  }

  load("high");
}

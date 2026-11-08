/** 首页：赛事介绍 / 组别 / 赛程 / 创作方向 / 公告。 */
import { api } from "../api.js?v=13";
import { h, fmtTime } from "../ui.js?v=13";
import { state, setNav } from "../app.js?v=13";

export async function render(app) {
  setNav("首页");
  const data = await api.get("/api/public/home");
  state.site = data.site;
  const { site, stats, groups } = data;

  app.innerHTML = "";

  /* ---- Hero ---- */
  app.append(h("section", { class: "hero" },
    h("span", { class: "hero-kicker" }, "🏆 2026年广东省青少年发明创新与科技实践活动"),
    h("h1", {}, "人工智能挑战类 · 人工智能应用"),
    h("div", { class: "theme" }, `赛事主题：${site.theme}`),
    h("p", { class: "desc" },
      "聚焦日常生活中的城市街道、社区生活与公共便民场景，鼓励同学们观察身边的智能化设备，依托人工智能思维，自主设计安全、便民、实用、美观的新型智慧设施，感知人工智能服务生活、改变生活的价值。"),
    h("div", { class: "hero-actions" },
      h("a", { class: "btn", href: "#/rules" }, "阅读竞赛规则"),
      h("a", { class: "btn outline", href: "#/scores" }, "成绩公示查询"),
      !state.user && h("a", { class: "btn outline", href: "#/login" }, "选手登录"),
      state.user?.role === "student" && h("a", { class: "btn outline", href: "#/me" }, "进入我的工作台"),
    ),
  ));

  /* ---- 数据带 ---- */
  app.append(h("div", { class: "statband" },
    ...Object.keys(groups).map((g) =>
      h("div", { class: "stat" },
        h("div", { class: "num" }, `${stats[g].total}`),
        h("div", { class: "lbl" }, `${groups[g]} · 已报名`))),
    h("div", { class: "stat" },
      h("div", { class: "num" }, `${stats.high.submitted}`),
      h("div", { class: "lbl" }, "已交卷")),
  ));

  /* ---- 组别设置 ---- */
  const groupCards = [
    { g: "high", tag: "小学 4—6 年级（3年级可自愿选报）", title: "知识测试 + 智能体作品（两部分合并评定）", points: ["知识测试：词元推理线上作答（框架/产生式表示法、演绎与归纳推理）", "智能体作品：围绕生活场景（图书馆、外卖订单、物流信息）设计智能体", "OJ 式操作台：配置知识库与回答模式，自动提交、AI 辅助判题", "客观题自动判分，创意类 AI 辅助打分允许部分得分，两部分成绩合并评定"] },
  ];
  app.append(h("div", { class: "section-head" }, h("h2", {}, "参赛组别与初赛内容")));
  app.append(h("div", { class: groupCards.length === 1 ? "grid" : "grid grid-3" },
    ...groupCards.map((c) => h("div", { class: "card group-card" },
      h("span", { class: "tag" }, c.tag),
      h("h3", {}, c.title),
      h("ul", {}, ...c.points.map((p) => h("li", {}, p))))),
  ));

  /* ---- 赛程 + 创作方向 ---- */
  app.append(h("div", { class: "section-head" }, h("h2", {}, "赛程安排与创作参考")));
  app.append(h("div", { class: "grid grid-2" },
    h("div", { class: "card" },
      h("div", { class: "card-title" }, h("h3", {}, "🗓️ 赛程安排")),
      h("p", { class: "ann-body", style: "padding-top:0" }, site.schedule || "以组委会通知为准"),
      data.submission.deadline && h("p", { class: "badge badge-warn" }, `作品提交截止：${fmtTime(data.submission.deadline)}`),
      h("p", { class: "small muted" }, site.contact || ""),
    ),
    h("div", { class: "card" },
      h("div", { class: "card-title" }, h("h3", {}, "💡 创作参考方向（不作限定）")),
      ...data.theme_directions.map((d) => h("div", { class: "mb8" },
        h("strong", {}, `${d.icon} ${d.title}`),
        h("div", { class: "dir-chips" }, ...d.items.map((i) => h("span", {}, i))))),
    ),
  ));

  /* ---- 公告 ---- */
  if (data.announcements.length) {
    app.append(h("div", { class: "section-head" }, h("h2", {}, "📢 通知公告")));
    const card = h("div", { class: "card" });
    for (const a of data.announcements) {
      card.append(h("div", { class: "ann-item" },
        a.pinned ? h("span", { class: "pin" }, "置顶") : "",
        h("span", { class: "t" }, a.title),
        h("span", { class: "d" }, fmtTime(a.created_at))));
      if (a.body) card.append(h("div", { class: "ann-body" }, a.body));
    }
    app.append(card);
  }
}

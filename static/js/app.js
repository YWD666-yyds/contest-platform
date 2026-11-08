/** 应用入口：会话状态 + hash 路由 + 导航渲染。 */
import { api } from "./api.js?v=13";
import { h, $, toastErr } from "./ui.js?v=13";
import * as home from "./pages/home.js?v=13";
import * as rules from "./pages/rules.js?v=13";
import * as scores from "./pages/scores.js?v=13";
import * as login from "./pages/login.js?v=13";
import * as student from "./pages/student.js?v=13";
import * as agentPage from "./pages/agent.js?v=13";
import * as exam from "./pages/exam.js?v=13";
import * as judge from "./pages/judge.js?v=13";
import * as admin from "./pages/admin.js?v=13";

export const state = {
  user: null,       // {id, username, role, must_change_pwd}
  student: null,    // 学生档案
  site: null,       // 站点设置（首页加载后填充）
};

// 供子页面在状态变更后强制整页重渲染（rerender 与子页面本地 render 不冲突）
export const rerender = () => route(true);

export const GROUP_NAMES = { high: "小学高段组" };  // 本届仅开放小学高段组

export async function refreshMe() {
  try {
    const data = await api.get("/api/auth/me");
    state.user = data.user;
    state.student = data.student || null;
  } catch {
    state.user = null; state.student = null;
  }
}

export function logout() {
  api.post("/api/auth/logout").finally(() => {
    state.user = null; state.student = null;
    lastHash = null;
    location.hash = "#/";
    route(true);
  });
}

/* ---------- 路由表 ---------- */
const routes = [
  { re: /^#\/$/, page: home, pub: true, nav: "首页" },
  { re: /^#\/rules/, page: rules, pub: true, nav: "比赛规则" },
  { re: /^#\/scores/, page: scores, pub: true, nav: "成绩公示" },
  { re: /^#\/login/, page: login, pub: true },
  { re: /^#\/me/, page: student, nav: "我的工作台", role: "student" },
  { re: /^#\/agent/, page: agentPage, role: "student" },
  { re: /^#\/exam/, page: exam, role: "student" },
  // 评委工作台已下线（本届评审由组委会教师线下开展）：路由保留用于直达提示页，不再进入导航
  { re: /^#\/judge/, page: judge, role: "judge,admin" },
  { re: /^#\/admin/, page: admin, nav: "管理后台", role: "admin" },
];

let currentNav = "";

export function setNav(name) { currentNav = name; renderNav(); }

function navItems() {
  const items = [];
  for (const r of routes) {
    if (!r.nav) continue;
    if (r.role) {
      const roles = r.role.split(",");
      if (!state.user || !roles.includes(state.user.role)) continue;
    }
    items.push(r);
  }
  return items;
}

function renderNav() {
  const items = navItems();
  const hrefMap = { "首页": "#/", "比赛规则": "#/rules", "成绩公示": "#/scores", "我的工作台": "#/me", "管理后台": "#/admin" };
  const desktop = $("#mainnav");
  const mobile = $("#mobile-nav");
  desktop.innerHTML = "";
  mobile.innerHTML = "";
  for (const r of items) {
    const href = hrefMap[r.nav] || "#/";
    for (const host of [desktop, mobile]) {
      host.append(h("a", { href, class: currentNav === r.nav ? "active" : "" }, r.nav));
    }
  }
  // 右侧用户区
  const right = $("#nav-user");
  right.innerHTML = "";
  if (state.user) {
    const roleText = { student: "选手", judge: "评委", admin: "管理员" }[state.user.role];
    right.append(
      h("span", { class: "userchip" },
        h("span", { class: "avatar" }, (state.student?.name || state.user.username).slice(0, 1)),
        h("span", {}, state.student ? `${state.student.name}（${state.student.entry_no}）` : state.user.username),
        h("span", { class: "badge badge-info" }, roleText)),
      h("button", { class: "btn btn-ghost btn-sm", onclick: logout }, "退出"),
    );
    if (state.user.must_change_pwd) {
      right.append(h("span", { class: "badge badge-warn" }, "请修改初始密码"));
    }
  } else {
    right.append(h("a", { class: "btn btn-sm", href: "#/login" }, "登录"));
  }
}

let renderToken = 0;
let lastHash = null;
let routing = false;

export async function route(force = false) {
  const hash = location.hash || "#/";
  // 防重复渲染：相同 hash 且上次渲染成功时跳过（部分环境会派发冗余 hashchange 事件）
  if (!force && (routing || (hash === lastHash && $("#app").dataset.rendered === "1"))) return;
  const app = $("#app");
  const token = ++renderToken;
  routing = true;
  try {
    for (const r of routes) {
      if (!r.re.test(hash)) continue;
      if (r.role) {
        const roles = r.role.split(",");
        if (!state.user || !roles.includes(state.user.role)) {
          location.hash = "#/login";
          return;
        }
      }
      renderNav();
      app.innerHTML = "";
      delete app.dataset.rendered;
      app.append(h("div", { class: "text-c muted", style: "padding:80px 0" }, "加载中…"));
      try {
        await r.page.render(app, hash);
        if (token === renderToken) { app.dataset.page = r.nav || ""; app.dataset.rendered = "1"; }
        window.scrollTo(0, 0);
      } catch (e) {
        if (token !== renderToken) return;
        app.innerHTML = "";
        app.append(h("div", { class: "card", style: "max-width:560px;margin:60px auto;text-align:center" },
          h("h3", {}, "页面加载失败"),
          h("p", { class: "muted" }, String(e.message || e)),
          h("button", { class: "btn", onclick: () => route(true) }, "重试")));
        toastErr(String(e.message || e));
      }
      lastHash = hash;
      return;
    }
    location.hash = "#/";
  } finally {
    routing = false;
  }
}

window.addEventListener("hashchange", route);
// 兜底：极少数环境可能丢失 hashchange 事件，轻量轮询检测（相同 hash 时路由守卫会直接跳过）
setInterval(() => {
  const h = location.hash || "#/";
  if (h !== lastHash) route();
}, 250);

(async function boot() {
  await refreshMe();
  try {
    const home0 = await api.get("/api/public/home");
    state.site = home0.site;
    $("#brand-title").textContent = "人工智能应用赛项";
    $("#brand-sub").textContent = home0.site.subtitle || "市级初赛平台";
    $("#footer-site").textContent = home0.site.title || "";
    $("#footer-contact").textContent = `赛事主题：${home0.site.theme} · ${home0.site.contact || ""}`;
    document.title = `${home0.site.title || "人工智能应用赛项"} · ${home0.site.subtitle || ""}`;
  } catch { /* 静态首页数据失败不阻塞 */ }
  renderNav();
  route();
})();

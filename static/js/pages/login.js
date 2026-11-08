/** 登录页：参赛编号/账号 + 密码，首登强制改密。 */
import { api } from "../api.js?v=12";
import { h, $, toastOk, toastErr } from "../ui.js?v=12";
import { state, refreshMe, setNav } from "../app.js?v=12";

export async function render(app) {
  setNav("");
  if (state.user) {
    location.hash = { student: "#/me", judge: "#/judge", admin: "#/admin" }[state.user.role] || "#/";
    return;
  }
  app.innerHTML = "";
  let mode = "login";

  const icon = h("div", { class: "big-icon" },
    h("svg", { viewBox: "0 0 24 24", width: 28, height: 28, fill: "none", stroke: "currentColor", "stroke-width": 2, "stroke-linecap": "round", "stroke-linejoin": "round" },
      h("path", { d: "M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" }),
      h("path", { d: "M10 17l5-5-5-5" }), h("path", { d: "M15 12H3" })));
  const tabs = h("div", { class: "auth-tabs" },
    h("button", { id: "tab-login", class: "active", onclick: () => switchMode("login") }, "登录"),
    h("button", { id: "tab-chg", onclick: () => switchMode("chg") }, "修改初始密码"));
  const formBox = h("div", { id: "form-box" });

  app.append(h("div", { class: "auth-wrap" },
    h("div", { class: "card auth-card" },
      h("div", { class: "auth-head" }, icon,
        h("h2", { style: "margin-bottom:4px" }, "选手 / 评委登录"),
        h("p", { class: "muted small" }, "选手使用参赛编号登录（由学校/组委会发放）")),
      tabs, formBox,
    )));

  function switchMode(m) {
    mode = m;
    $("#tab-login").classList.toggle("active", m === "login");
    $("#tab-chg").classList.toggle("active", m === "chg");
    formBox.innerHTML = "";
    formBox.append(m === "login" ? loginForm() : changeForm());
  }

  function loginForm() {
    const err = h("p", { class: "small", style: "color:var(--danger);min-height:18px;margin:6px 0 0" });
    const username = h("input", { class: "input", placeholder: "参赛编号 / 账号名", autocomplete: "username" });
    const password = h("input", { class: "input", type: "password", placeholder: "密码", autocomplete: "current-password",
      onkeydown: (e) => { if (e.key === "Enter") doLogin(); } });
    async function doLogin() {
      err.textContent = "";
      if (!username.value.trim() || !password.value) { err.textContent = "请输入账号和密码"; return; }
      try {
        const data = await api.post("/api/auth/login", { username: username.value.trim(), password: password.value });
        toastOk("登录成功");
        await refreshMe();
        if (state.user.must_change_pwd) { switchMode("chg"); return; }
        location.hash = { student: "#/me", judge: "#/judge", admin: "#/admin" }[data.role] || "#/";
      } catch (e) { err.textContent = e.message; }
    }
    return h("div", {},
      h("div", { class: "field" }, h("label", {}, "账号"), username),
      h("div", { class: "field" }, h("label", {}, "密码"), password),
      err,
      h("button", { class: "btn btn-block btn-lg", onclick: doLogin }, "登 录"),
      h("p", { class: "small muted mt16 text-c" }, "忘记密码请联系学校或组委会管理员重置"),
    );
  }

  function changeForm() {
    const err = h("p", { class: "small", style: "color:var(--danger);min-height:18px;margin:6px 0 0" });
    const oldp = h("input", { class: "input", type: "password", placeholder: "当前密码 / 初始密码" });
    const newp = h("input", { class: "input", type: "password", placeholder: "新密码（至少 8 位）" });
    const newp2 = h("input", { class: "input", type: "password", placeholder: "再次输入新密码" });
    async function doChange() {
      err.textContent = "";
      if (newp.value.length < 8) { err.textContent = "新密码至少 8 位"; return; }
      if (newp.value !== newp2.value) { err.textContent = "两次输入的新密码不一致"; return; }
      try {
        await api.post("/api/auth/change-password", { old_password: oldp.value, new_password: newp.value });
        toastOk("密码修改成功，请使用新密码重新登录");
        await api.post("/api/auth/logout");
        await refreshMe();
        switchMode("login");
      } catch (e) { err.textContent = e.message; }
    }
    return h("div", {},
      h("div", { class: "field" }, h("label", {}, "当前密码"), oldp),
      h("div", { class: "field" }, h("label", {}, "新密码"), newp),
      h("div", { class: "field" }, h("label", {}, "确认新密码"), newp2),
      err,
      h("button", { class: "btn btn-block btn-lg", onclick: doChange }, "确认修改"),
      h("p", { class: "small muted mt16 text-c" }, "首次登录须修改初始密码"),
    );
  }

  switchMode("login");
}

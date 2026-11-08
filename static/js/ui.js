/** UI 工具：元素构建、toast、modal、格式化。 */

export function h(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k === "value") node.value = v;   // textarea / input 通用（textarea 无 value 内容属性）
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else if (k === "checked" || k === "disabled" || k === "selected") node[k] = v;
    else node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c == null || c === false) continue;
    node.append(c.nodeType ? c : document.createTextNode(c));
  }
  return node;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/* ---------- toast ---------- */
export function toast(msg, type = "info", ms = 3200) {
  const root = $("#toast-root");
  const el = h("div", { class: `toast toast-${type}` }, msg);
  root.append(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, ms - 300);
  setTimeout(() => el.remove(), ms);
}
export const toastOk = (m) => toast(m, "ok");
export const toastErr = (m) => toast(m, "err", 4200);

/* ---------- modal ---------- */
export function modal({ title, body, actions, wide = false, onClose }) {
  const root = $("#modal-root");
  const close = () => { mask.remove(); onClose && onClose(); };
  const mask = h("div", { class: "modal-mask", onclick: (e) => { if (e.target === mask) close(); } },
    h("div", { class: "modal" + (wide ? " wide" : "") },
      title && h("h3", {}, title),
      typeof body === "function" ? body(close) : body,
      actions && h("div", { class: "modal-actions" }, ...actions(close)),
    ));
  root.append(mask);
  return close;
}

export function confirmBox(text, onYes, { danger = false, yes = "确定", no = "取消" } = {}) {
  modal({
    body: h("p", { style: "font-size:15px" }, text),
    actions: (close) => [
      h("button", { class: "btn btn-ghost", onclick: close }, no),
      h("button", { class: "btn" + (danger ? " btn-danger" : ""), onclick: () => { close(); onYes(); } }, yes),
    ],
  });
}

/* ---------- 图片放大 ---------- */
export function lightbox(src) {
  const mask = h("div", { class: "lightbox-mask", onclick: () => mask.remove() },
    h("img", { src, alt: "查看大图" }));
  document.body.append(mask);
}

/* ---------- 格式化 ---------- */
export function fmtTime(s) {
  if (!s) return "—";
  return s.slice(0, 16).replace("T", " ");
}
export function fmtDur(sec) {
  if (sec == null) return "—";
  const m = Math.floor(sec / 60), s = sec % 60;
  const hh = Math.floor(m / 60);
  return hh ? `${hh}时${String(m % 60).padStart(2, "0")}分${String(s).padStart(2, "0")}秒`
            : `${m}分${String(s).padStart(2, "0")}秒`;
}
export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

/* ---------- 状态徽章 ---------- */
export function badge(text, type = "off") {
  return h("span", { class: `badge badge-${type}` }, text);
}
export const statusBadge = (status, extra) => {
  if (extra === "disqualified") return badge("已取消资格", "danger");
  if (status === "submitted") return badge("已提交", "ok");
  return badge("未提交", "off");
};

/* ---------- 空状态 ---------- */
export function empty(text = "暂无数据") {
  return h("div", { class: "text-c muted", style: "padding:40px 0" }, text);
}

/* ---------- 复制文本 ---------- */
export function copyText(text) {
  navigator.clipboard?.writeText(text).then(
    () => toastOk("已复制"),
    () => toastErr("复制失败"),
  );
}

/* ---------- 自绘下拉（替代原生 select：内嵌浏览器原生弹出层定位有偏差） ---------- */
export function dropdown({ options, value, onChange, cls = "" }) {
  const find = (v) => options.find((o) => o.v === v);
  const cur = find(value) || options[0];
  const curLabel = h("span", { class: "dropdown-cur" }, cur ? cur.t : "");
  const menu = h("div", { class: "dropdown-menu" });
  const root = h("div", { class: "dropdown " + cls },
    h("button", { type: "button", class: "dropdown-btn" }, curLabel, h("span", { class: "dropdown-caret" }, "▾")),
    menu);

  function mark(v) {
    $$(".dropdown-item", menu).forEach((it) => it.classList.toggle("active", it.dataset.v === v));
    const opt = find(v);
    curLabel.textContent = opt ? opt.t : "";
  }
  for (const o of options) {
    menu.append(h("div", { class: "dropdown-item" + (o.v === value ? " active" : ""), "data-v": o.v,
      onclick: () => { root.setValue(o.v); closeDropdowns(); onChange && onChange(o.v); } }, o.t));
  }
  mark(value);
  root.querySelector(".dropdown-btn").addEventListener("click", (e) => {
    e.stopPropagation();
    const open = menu.style.display === "block";
    closeDropdowns();
    menu.style.display = open ? "none" : "block";
  });
  root.setValue = (v) => mark(v);
  root.getValue = () => { const it = $(".dropdown-item.active", menu); return it ? it.dataset.v : (cur ? cur.v : ""); };
  return root;
}

export function closeDropdowns() {
  $$(".dropdown-menu").forEach((m) => { m.style.display = "none"; });
}
document.addEventListener("click", () => closeDropdowns());

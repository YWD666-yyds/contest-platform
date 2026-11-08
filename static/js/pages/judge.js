/** 评审工作台（已下线）：本届评审由组委会教师线下开展，此页仅展示说明。 */
import { h } from "../ui.js?v=13";
import { setNav } from "../app.js?v=13";

export async function render(app) {
  setNav("");
  app.innerHTML = "";
  app.append(h("div", { class: "card lock-screen", style: "max-width:560px;margin:40px auto" },
    h("div", { style: "font-size:46px" }, "🧑‍⚖️"),
    h("h2", {}, "评委工作台未启用"),
    h("p", { class: "muted" },
      "本届赛事的评审由组委会教师线下开展：智能体作品的 AI 检测与人工复核在管理后台「智能体任务」中完成，"
      + "知识测试成绩由系统自动判分。评委账号无需在此操作。"),
    h("p", { class: "small muted mt8" },
      "如有疑问请联系组委会管理员。"),
  ));
}

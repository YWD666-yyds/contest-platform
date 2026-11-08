"""初始化：管理员账号 + 内置样题题库（依据竞赛规则与教师培训 PPT 知识点）。

运行：python -m app.seed
"""
import json

from . import config
from .db import get_db, init_db
from .security import hash_password

JUDGE_OPTS = [{"key": "A", "text": "正确"}, {"key": "B", "text": "错误"}]


def q(group, type_, stem, options, answer, topic, score):
    return {
        "group_code": group, "type": type_, "stem": stem,
        "options": json.dumps(options, ensure_ascii=False),
        "answer": json.dumps(answer), "score": score, "topic": topic,
    }


# ============ 小学高段组样题（框架表示法 / 产生式表示法 / 演绎、归纳推理 / 伦理） ============
HIGH = [
    q("high", "judge", "知识表示就是把现实世界中的事物及其关系，转化为计算机能够存储、处理的符号结构。",
      JUDGE_OPTS, ["A"], "知识表示概念", 1),
    q("high", "single", "用框架表示法描述「外卖订单」时，「配送地址：环湖小区1栋101」中，「配送地址」属于框架的什么部分？",
      [{"key": "A", "text": "框架名称"}, {"key": "B", "text": "槽位（属性）"},
       {"key": "C", "text": "填充内容（值）"}, {"key": "D", "text": "侧面"}],
      ["B"], "框架表示法", 2),
    q("high", "single", "下列哪类知识最适合用框架表示法来描述？",
      [{"key": "A", "text": "一份外卖订单的顾客、地址、菜品等信息"},
       {"key": "B", "text": "城市明天会不会下雨"},
       {"key": "C", "text": "解数学题的计算步骤"},
       {"key": "D", "text": "同学之间的友谊"}],
      ["A"], "框架表示法", 2),
    q("high", "single", "产生式表示法的基本形式是「IF 条件 THEN 结论」，其中 IF 部分称为：",
      [{"key": "A", "text": "前件（条件）"}, {"key": "B", "text": "后件（结论）"},
       {"key": "C", "text": "事实"}, {"key": "D", "text": "槽位"}],
      ["A"], "产生式表示法", 2),
    q("high", "multiple", "一个产生式系统通常由哪些部分组成？",
      [{"key": "A", "text": "事实库"}, {"key": "B", "text": "规则库"},
       {"key": "C", "text": "推理机（控制系统）"}, {"key": "D", "text": "显示器"}],
      ["A", "B", "C"], "产生式表示法", 3),
    q("high", "judge", "产生式系统中，存放所有 IF-THEN 规则的集合称为规则库。",
      JUDGE_OPTS, ["A"], "产生式表示法", 1),
    q("high", "single", "推理机的作用是：",
      [{"key": "A", "text": "存储当前已知的信息"},
       {"key": "B", "text": "用事实去匹配规则的条件，匹配成功就触发对应的后件"},
       {"key": "C", "text": "把规则画成语义网络"},
       {"key": "D", "text": "收集用户的个人隐私"}],
      ["B"], "产生式表示法", 2),
    q("high", "single", "规则库：R1：IF 有毛发 THEN 哺乳动物；R5：IF 哺乳动物 AND 吃肉 THEN 食肉动物。当前事实库只有「有毛发、吃肉」两条事实，正向推理第一轮会先得出哪个新事实？",
      [{"key": "A", "text": "食肉动物"}, {"key": "B", "text": "哺乳动物"},
       {"key": "C", "text": "猎豹"}, {"key": "D", "text": "老虎"}],
      ["B"], "产生式推理", 2),
    q("high", "single", "演绎推理（三段论）「所有三角形内角和是180°，直角三角形是三角形，所以直角三角形内角和是180°」中，「所有三角形内角和是180°」是：",
      [{"key": "A", "text": "大前提（一般规律）"}, {"key": "B", "text": "小前提（具体事物）"},
       {"key": "C", "text": "结论"}, {"key": "D", "text": "假设"}],
      ["A"], "演绎推理", 2),
    q("high", "judge", "演绎推理是从一般推出特殊（个别），归纳推理是从多个特殊事例中总结出一般规律。",
      JUDGE_OPTS, ["A"], "演绎与归纳推理", 1),
    q("high", "single", "小明发现周一到周五早上8点小区门口都堵车，于是总结出「工作日早8点小区门口容易堵车」。这属于哪种推理？",
      [{"key": "A", "text": "演绎推理"}, {"key": "B", "text": "归纳推理"},
       {"key": "C", "text": "逆向推理"}, {"key": "D", "text": "冲突消解"}],
      ["B"], "归纳推理", 2),
    q("high", "single", "「只见过会飞的鸟，就断言『所有的鸟都会飞』」，这种以偏概全、不客观的问题在人工智能伦理中称为：",
      [{"key": "A", "text": "隐私问题"}, {"key": "B", "text": "偏见问题"},
       {"key": "C", "text": "版权问题"}, {"key": "D", "text": "网络安全问题"}],
      ["B"], "人工智能伦理", 2),
    q("high", "judge", "在学生画像框架中记录家庭住址、身份证号等与学习无关的敏感信息且未经同意，属于隐私问题。",
      JUDGE_OPTS, ["A"], "人工智能伦理", 1),
    q("high", "single", "用框架表示「评价学生」时，如果只有「考试分数」一个槽，没有品德、兴趣、特长等槽位，最主要的问题是：",
      [{"key": "A", "text": "对学生的认识片面、不客观（偏见）"},
       {"key": "B", "text": "框架名称不够好听"},
       {"key": "C", "text": "计算机运行速度会变快"},
       {"key": "D", "text": "没有违反任何原则"}],
      ["A"], "人工智能伦理", 2),
    q("high", "single", "关于确定性推理，下列说法正确的是：",
      [{"key": "A", "text": "前提为真时，结论或者为「真」或者为「假」，没有第三种情况"},
       {"key": "B", "text": "结论只能是可能为真"},
       {"key": "C", "text": "结论永远为真"},
       {"key": "D", "text": "结论与前提无关"}],
      ["A"], "推理概念", 2),
    q("high", "single", "AI 填写外卖订单框架后，配送员 App 能直接取出「配送地址」槽位的内容进行导航。这说明框架表示法的优点是：",
      [{"key": "A", "text": "结构固定、属性明确，便于机器直接提取和运用"},
       {"key": "B", "text": "可以表达不确定的情感"},
       {"key": "C", "text": "必须联网才能使用"},
       {"key": "D", "text": "信息量一定比自然语言多"}],
      ["A"], "框架表示法", 2),
]

def run():
    init_db()
    with get_db() as conn:
        # 管理员
        if not conn.execute("SELECT 1 FROM users WHERE role='admin' LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO users(username,password_hash,role,must_change_pwd) VALUES(?,?,?,0)",
                ("admin", hash_password(config.ADMIN_INITIAL_PASSWORD), "admin"),
            )
            print(f"已创建管理员：admin / {config.ADMIN_INITIAL_PASSWORD}")
        # 样题
        if not conn.execute("SELECT 1 FROM questions LIMIT 1").fetchone():
            for item in HIGH:
                conn.execute(
                    "INSERT INTO questions(group_code,type,stem,options,answer,score,topic) "
                    "VALUES(:group_code,:type,:stem,:options,:answer,:score,:topic)",
                    item,
                )
            print(f"已导入样题：小学高段组 {len(HIGH)} 题")
        # 欢迎公告
        if not conn.execute("SELECT 1 FROM announcements LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO announcements(title,body,pinned) VALUES(?,?,1)",
                ("欢迎使用本市级初赛平台",
                 "请先阅读「比赛规则」栏目，小学高段组选手按本站考试安排参加线上作答，"
                 "并在「设计智能体」中完成实操任务。祝各位选手取得优异成绩！"),
            )
    print("初始化完成。")


if __name__ == "__main__":
    run()

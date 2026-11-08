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

# ============ 中学组样题（高段内容 + 谓词逻辑 / 语义网络 / 正向逆向 / 冲突消解 / 搜索策略） ============
MIDDLE = [
    q("middle", "judge", "谓词逻辑中，谓词刻画个体的性质或关系，取值为真或假。",
      JUDGE_OPTS, ["A"], "谓词逻辑", 1),
    q("middle", "single", "「所有学生都应遵守规则」的谓词公式是：",
      [{"key": "A", "text": "∀x(Student(x) → ShouldObeyRules(x))"},
       {"key": "B", "text": "∃x(Student(x) ∧ ShouldObeyRules(x))"},
       {"key": "C", "text": "ShouldObeyRules(Student)"},
       {"key": "D", "text": "∀x(Student(x) ∧ ShouldObeyRules(x))"}],
      ["A"], "谓词逻辑", 2),
    q("middle", "single", "「小蕊乘地铁去学校」用谓词 Take(XiaoRui, Subway, School) 表示，这是一个：",
      [{"key": "A", "text": "一元谓词"}, {"key": "B", "text": "二元谓词"},
       {"key": "C", "text": "三元谓词"}, {"key": "D", "text": "语义网络"}],
      ["C"], "谓词逻辑", 2),
    q("middle", "single", "谓词逻辑符号中，∃ 表示：",
      [{"key": "A", "text": "全称量词（所有）"}, {"key": "B", "text": "存在量词（有一个）"},
       {"key": "C", "text": "否定"}, {"key": "D", "text": "并且"}],
      ["B"], "谓词逻辑", 2),
    q("middle", "single", "已知推理规则 ∀x(HUMAN(x) → THINK(x))，再已知事实 HUMAN(小明)，可以推出：",
      [{"key": "A", "text": "THINK(小明)"}, {"key": "B", "text": "HUMAN(所有学生)"},
       {"key": "C", "text": "¬THINK(小明)"}, {"key": "D", "text": "无法推出任何结论"}],
      ["A"], "谓词逻辑", 2),
    q("middle", "judge", "语义网络中，ISA 弧表示「实例→类」的关系，如「咪咪 ISA 猫」，弧由个体指向类。",
      JUDGE_OPTS, ["A"], "语义网络", 1),
    q("middle", "single", "语义网络中，「猫 AKO 哺乳动物」表示的是：",
      [{"key": "A", "text": "猫是哺乳动物的一个实例"},
       {"key": "B", "text": "猫类属于哺乳动物这个父类（类属关系）"},
       {"key": "C", "text": "猫拥有哺乳动物"},
       {"key": "D", "text": "哺乳动物是猫的一部分"}],
      ["B"], "语义网络", 2),
    q("middle", "single", "在语义网络中沿 AKO 弧向上走，可以：",
      [{"key": "A", "text": "继承父类的属性，如「猫 AKO 哺乳动物」，猫继承「哺乳」等属性"},
       {"key": "B", "text": "删除所有节点"},
       {"key": "C", "text": "把类变成个体"},
       {"key": "D", "text": "提高网络传输速度"}],
      ["A"], "语义网络", 2),
    q("middle", "multiple", "下列属于知识表示方法的有：",
      [{"key": "A", "text": "框架表示法"}, {"key": "B", "text": "产生式表示法"},
       {"key": "C", "text": "谓词逻辑表示法"}, {"key": "D", "text": "语义网络表示法"}],
      ["A", "B", "C", "D"], "知识表示概念", 3),
    q("middle", "single", "正向推理的特点是：",
      [{"key": "A", "text": "从已知事实出发，用规则不断推出新事实并加入事实库（数据驱动）"},
       {"key": "B", "text": "先假设结论成立，再寻找支持这个结论的证据（目标驱动）"},
       {"key": "C", "text": "随机挑选规则执行"},
       {"key": "D", "text": "只执行最后一条规则"}],
      ["A"], "正向与逆向推理", 2),
    q("middle", "single", "医生先假设病人「可能患普通感冒」，再逐项核对症状、体温等证据来验证，这种推理方式更接近：",
      [{"key": "A", "text": "正向推理"}, {"key": "B", "text": "逆向推理"},
       {"key": "C", "text": "宽度优先搜索"}, {"key": "D", "text": "归纳推理"}],
      ["B"], "正向与逆向推理", 2),
    q("middle", "single", "正向推理中，多条规则的条件同时满足时，需要决定先执行哪条，这一过程称为：",
      [{"key": "A", "text": "冲突消解"}, {"key": "B", "text": "知识表示"},
       {"key": "C", "text": "框架填槽"}, {"key": "D", "text": "语义解析"}],
      ["A"], "冲突消解", 2),
    q("middle", "single", "下列哪一项不是常用的冲突消解策略？",
      [{"key": "A", "text": "优先执行条件更特殊（限定更多）的规则"},
       {"key": "B", "text": "优先执行最近刚执行过的规则（新鲜度优先）"},
       {"key": "C", "text": "按规则编号顺序执行"},
       {"key": "D", "text": "所有命中规则都不执行，直接结束"}],
      ["D"], "冲突消解", 2),
    q("middle", "judge", "深度优先搜索（DFS）是一条路走到黑、走不通再回溯；宽度优先搜索（BFS）是先看完本层所有节点再进入下一层。",
      JUDGE_OPTS, ["A"], "搜索策略", 1),
    q("middle", "single", "搜索树：根节点 S，S 的子节点为 A、B；A 的子节点为 C、D。用宽度优先搜索（BFS）从 S 出发，访问顺序是：",
      [{"key": "A", "text": "S → A → C → D → B"},
       {"key": "B", "text": "S → A → B → C → D"},
       {"key": "C", "text": "S → B → A → D → C"},
       {"key": "D", "text": "S → C → D → A → B"}],
      ["B"], "搜索策略", 2),
    q("middle", "single", "用深度优先搜索（DFS）遍历上面的同一棵树（子节点按从左到右访问），访问顺序是：",
      [{"key": "A", "text": "S → A → C → D → B"},
       {"key": "B", "text": "S → A → B → C → D"},
       {"key": "C", "text": "S → B → A → C → D"},
       {"key": "D", "text": "S → B → D → C → A"}],
      ["A"], "搜索策略", 2),
    q("middle", "multiple", "下列属于盲目搜索（无启发式信息）的有：",
      [{"key": "A", "text": "深度优先搜索"}, {"key": "B", "text": "宽度优先搜索"},
       {"key": "C", "text": "依据提示屏指示灯优先查找的启发式搜索"}, {"key": "D", "text": "依赖启发式信息的A*搜索"}],
      ["A", "B"], "搜索策略", 3),
    q("middle", "single", "规则库：R1：IF 有毛发 THEN 哺乳动物；R5：IF 哺乳动物 AND 吃肉 THEN 食肉动物；R6：IF 食肉动物 AND 黄褐色 AND 有暗斑点 THEN 猎豹。初始事实：有毛发、吃肉、黄褐色、有暗斑点。正向推理得出「猎豹」的过程中，三条规则的触发顺序是：",
      [{"key": "A", "text": "R6 → R5 → R1"}, {"key": "B", "text": "R1 → R5 → R6"},
       {"key": "C", "text": "R5 → R1 → R6"}, {"key": "D", "text": "R1 → R6 → R5"}],
      ["B"], "产生式推理", 2),
    q("middle", "single", "产生式表示法中，「IF 环境亮度=较暗 THEN 自动调高灯光亮度」，与该规则对应呈现相反情形的合理规则是：",
      [{"key": "A", "text": "IF 环境亮度=较亮 THEN 自动调低灯光亮度"},
       {"key": "B", "text": "IF 自动调高灯光 THEN 环境亮度=较暗"},
       {"key": "C", "text": "IF 环境亮度=较暗 THEN 关闭电源"},
       {"key": "D", "text": "THEN 环境亮度=较暗 IF 自动调高灯光亮度"}],
      ["A"], "产生式表示法", 2),
    q("middle", "judge", "知识表示与知识推理是知识工程的两块基石：表示让机器「读懂」知识，推理让机器「学会思考」。",
      JUDGE_OPTS, ["A"], "知识工程概念", 1),
    q("middle", "single", "处理人工智能伦理情景题的「三步答题法」中，第二步「判类型」是要判断问题属于：",
      [{"key": "A", "text": "偏见（不客观）还是隐私（过度收集、未授权）"},
       {"key": "B", "text": "物理问题还是化学问题"},
       {"key": "C", "text": "数学问题还是语文问题"},
       {"key": "D", "text": "硬件问题还是软件问题"}],
      ["A"], "人工智能伦理", 2),
    q("middle", "single", "把「Lucy 和 Lily 是姐妹」表示为谓词公式，正确的形式是：",
      [{"key": "A", "text": "Sister(Lucy, Lily)"}, {"key": "B", "text": "Lucy(Sister, Lily)"},
       {"key": "C", "text": "∀x Sister(x)"}, {"key": "D", "text": "Sister ∧ Lucy ∧ Lily"}],
      ["A"], "谓词逻辑", 2),
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
            for item in HIGH + MIDDLE:
                conn.execute(
                    "INSERT INTO questions(group_code,type,stem,options,answer,score,topic) "
                    "VALUES(:group_code,:type,:stem,:options,:answer,:score,:topic)",
                    item,
                )
            print(f"已导入样题：高段组 {len(HIGH)} 题、中学组 {len(MIDDLE)} 题")
        # 欢迎公告
        if not conn.execute("SELECT 1 FROM announcements LIMIT 1").fetchone():
            conn.execute(
                "INSERT INTO announcements(title,body,pinned) VALUES(?,?,1)",
                ("欢迎使用本市级初赛平台",
                 "请先阅读「比赛规则」栏目，小学低段组选手在「我的工作台」提交作品材料，"
                 "小学高段组与中学组选手按考试安排参加线上作答。祝各位选手取得优异成绩！"),
            )
    print("初始化完成。")


if __name__ == "__main__":
    run()

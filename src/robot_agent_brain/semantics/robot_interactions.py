import re


class RobotInteractionLexicon:
    """One interaction vocabulary shared by prompting and domain validation."""
    terms = {
        "grasp": ("抓", "夹住", "夹起"),
        "pick": ("拿起", "拿出", "取出", "提起"),
        "take": ("拿走", "取走"),
        "release": ("释放", "松开"),
        "place": ("放进", "放入", "放到", "放置", "放下"),
        "press": ("按下", "按压", "按按钮"),
        "push": ("推动", "推开", "推一下"),
        "pull": ("拉动", "拉开", "拉一下"),
        "open": ("打开", "开启"),
        "close": ("关闭", "关上"),
    }

    @classmethod
    def matches(cls, text):
        text = text.casefold()
        return any(re.search(r"\b" + key + r"\b", text) or any(term in text for term in terms)
                   for key, terms in cls.terms.items())

    @classmethod
    def prompt_rules(cls):
        return "机器人交互动词词表（按完整动作语义使用，不把否定、引用或查询当命令）：\n" + "\n".join(
            f"{key}: {'、'.join(terms)}" for key, terms in cls.terms.items())

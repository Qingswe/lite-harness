#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看板呈现层的契约断言。

「审美好」「层级清晰」「图看得懂」都不能直接断言，所以每一条这样的诉求在这里
都被换成一个能从仓库文件算出来的代理指标。本脚本是那些指标的执行体，也是
`refresh-harness-dashboard-visual-language` 的验证证据产出方式。

    check-dashboard-contract.py tokens     设计变量：色相、字体、行高、栅格、对比度
    check-dashboard-contract.py layout     版式：字号阶梯、彩色预算、字距、删除线
    check-dashboard-contract.py nav        导航树：点击深度、树深、覆盖、首屏展开
    check-dashboard-contract.py graphs     图形：流程图完整性、关系图与源数据一致
    check-dashboard-contract.py evidence   证据分类与图片内联（后续 change 填充）
    check-dashboard-contract.py roles      角色档案（后续 change 填充）
    check-dashboard-contract.py all        以上全部

任一断言失败即以非零码退出。`--json <路径>` 把完整结果写成证据文件。
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime

_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

ROOT = os.path.dirname(os.path.dirname(_SELF_DIR))
DASHBOARD_DIR = os.path.join(ROOT, ".harness", "dashboard")
THEME_CSS = os.path.join(DASHBOARD_DIR, "theme.css")
APP_JS = os.path.join(DASHBOARD_DIR, "app.js")
GRAPH_JS = os.path.join(DASHBOARD_DIR, "graph.js")


# --------------------------------------------------------------------------
# 断言结果模型
# --------------------------------------------------------------------------

class Report(object):
    """一组断言的结果。

    每条都带实测值与期望值：失败时人要能直接看出差多少，而不是只知道「不通过」。
    """

    def __init__(self, group):
        self.group = group
        self.checks = []

    def add(self, check_id, description, actual, expected, ok, detail=None):
        self.checks.append({
            "id": check_id,
            "group": self.group,
            "description": description,
            "actual": actual,
            "expected": expected,
            "ok": bool(ok),
            "detail": detail or [],
        })
        return ok

    def expect_equal(self, check_id, description, actual, expected, detail=None):
        return self.add(check_id, description, actual, expected,
                        actual == expected, detail)

    def expect_at_least(self, check_id, description, actual, minimum,
                        detail=None):
        ok = actual is not None and actual >= minimum
        return self.add(check_id, description, actual, "≥ %s" % minimum, ok,
                        detail)

    @property
    def failed(self):
        return [c for c in self.checks if not c["ok"]]


def print_report(reports):
    total = failed = 0
    for report in reports:
        for check in report.checks:
            total += 1
            mark = "  ok  " if check["ok"] else " FAIL "
            if not check["ok"]:
                failed += 1
            print("[%s] %-7s %s" % (mark, check["id"], check["description"]))
            print("           实测: %s" % _fmt(check["actual"]))
            print("           期望: %s" % _fmt(check["expected"]))
            for line in check["detail"][:20]:
                print("           · %s" % line)
            extra = len(check["detail"]) - 20
            if extra > 0:
                print("           · …另有 %d 条" % extra)
    print("")
    print("%d 条断言，%d 条失败。" % (total, failed))
    return failed


def _fmt(value):
    if isinstance(value, (list, tuple, set)):
        items = sorted(value, key=str)
        if len(items) > 8:
            return "%s …（共 %d 项）" % (", ".join(str(x) for x in items[:8]),
                                        len(items))
        return ", ".join(str(x) for x in items) or "（空）"
    return str(value)


# --------------------------------------------------------------------------
# CSS 解析
# --------------------------------------------------------------------------

_COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)
_DECL_RE = re.compile(r"([-\w]+)\s*:\s*([^;{}]+)")


class Rule(object):
    def __init__(self, selector, body, line):
        self.selector = selector.strip()
        self.body = body
        self.line = line

    @property
    def is_root(self):
        # token 定义块。浅色主题的覆盖写在 @media 里，但选择器同样是 :root，
        # 而 parse_css 会把 at-rule 的内层规则平铺出来，所以这一条就够。
        return all(part.strip() == ":root" for part in self.selector.split(","))

    def declarations(self):
        return [(m.group(1).strip().lower(), m.group(2).strip())
                for m in _DECL_RE.finditer(self.body)]


def parse_css(path):
    """把样式表切成规则块。

    不做完整 CSS 解析——只需要「选择器 + 声明体」这一层，@media 等 at-rule 的
    内层规则会被平铺出来，这正是断言想要的粒度。
    """
    text = _COMMENT_RE.sub("", _read(path))
    rules = []
    depth_stack = []
    buf = ""
    line = 1
    selector = ""
    for ch in text:
        if ch == "\n":
            line += 1
        if ch == "{":
            selector = buf.strip()
            buf = ""
            depth_stack.append((selector, line))
            continue
        if ch == "}":
            if depth_stack:
                sel, start = depth_stack.pop()
                if not sel.startswith("@"):
                    rules.append(Rule(sel, buf, start))
            buf = ""
            continue
        buf += ch
    return rules


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


_VAR_RE = re.compile(r"var\(\s*(--[\w-]+)\s*(?:,([^()]*))?\)")


def collect_tokens(rules):
    """把全部 :root 块里的 token 收成一张表。

    没有这一步，断言会全部变成空转：间距现在写作 var(--s2)，直接扫 px 字面量
    只会得到「0 条违规 / 共 0 条」——一条什么都没查却报绿的断言。
    """
    tokens = {}
    for rule in rules:
        if not rule.is_root:
            continue
        for name, value in rule.declarations():
            if name.startswith("--"):
                tokens.setdefault(name, value.strip())
    return tokens


def resolve_vars(value, tokens, depth=0):
    """把 var(--x) 递归替换成 token 的实际取值。"""
    if depth > 8 or "var(" not in value:
        return value

    def sub(match):
        name, fallback = match.group(1), match.group(2)
        if name in tokens:
            return tokens[name]
        return (fallback or "").strip()

    return resolve_vars(_VAR_RE.sub(sub, value), tokens, depth + 1)


# --------------------------------------------------------------------------
# 颜色
# --------------------------------------------------------------------------

_HEX_RE = re.compile(r"#([0-9a-fA-F]{3,8})\b")
_FUNC_RE = re.compile(r"\b(rgba?|hsla?)\(([^)]*)\)")


def parse_hex(token):
    if len(token) == 3:
        token = "".join(c * 2 for c in token)
    if len(token) in (4, 8):  # 带 alpha，取前三段
        token = token[:6]
    if len(token) != 6:
        return None
    return tuple(int(token[i:i + 2], 16) for i in (0, 2, 4))


def parse_color_functions(value):
    """从一段声明值里取出 rgb()/hsl() 形式的颜色。

    只认真正的颜色函数；`color-mix(in srgb, var(--act) 18%, transparent)`
    这种基于 token 的派生不含独立色值，不应被当成字面量。
    """
    out = []
    for match in _FUNC_RE.finditer(value):
        kind = match.group(1)
        parts = [p.strip() for p in re.split(r"[,\s/]+", match.group(2)) if p.strip()]
        try:
            if kind.startswith("rgb"):
                out.append(tuple(int(float(p.rstrip("%"))) for p in parts[:3]))
            else:
                hue = float(parts[0].rstrip("deg"))
                sat = float(parts[1].rstrip("%")) / 100.0
                lig = float(parts[2].rstrip("%")) / 100.0
                out.append(hsl_to_rgb(hue, sat, lig))
        except (ValueError, IndexError):
            continue
    return out


def colors_in(value):
    """一段声明值里的全部颜色字面量。"""
    out = []
    for match in _HEX_RE.finditer(value):
        rgb = parse_hex(match.group(1))
        if rgb:
            out.append(rgb)
    out.extend(parse_color_functions(value))
    return out


def hsl_to_rgb(hue, sat, lig):
    import colorsys
    r, g, b = colorsys.hls_to_rgb((hue % 360) / 360.0, lig, sat)
    return (int(round(r * 255)), int(round(g * 255)), int(round(b * 255)))


def rgb_to_hsl(rgb):
    import colorsys
    r, g, b = (c / 255.0 for c in rgb)
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return (h * 360.0, s, l)


def chroma(rgb):
    """彩度 = (max - min) / 255。

    刻意不用 HSL 的饱和度：它在接近纯白或纯黑时会趋近 1，于是 #F5F4EE 这种
    暖白会被判成「彩色」。彩度不受亮度影响，能干净地把中性色阶分出去。
    """
    return (max(rgb) - min(rgb)) / 255.0


def relative_luminance(rgb):
    """WCAG 2.x 相对亮度。"""
    channels = []
    for value in rgb:
        c = value / 255.0
        channels.append(c / 12.92 if c <= 0.03928
                        else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = channels
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg, bg):
    a, b = relative_luminance(fg), relative_luminance(bg)
    lighter, darker = max(a, b), min(a, b)
    return (lighter + 0.05) / (darker + 0.05)


def hex_of(rgb):
    return "#%02X%02X%02X" % rgb


# --------------------------------------------------------------------------
# 子命令（各组断言在后续任务里逐条填充）
# --------------------------------------------------------------------------

CHROMA_FLOOR = 0.12          # 彩度低于这条线算中性色，不占彩色配额
CHROMATIC_TOKENS = ("--act", "--pass", "--fail")
HUE_SEPARATION_FLOOR = 20.0  # 三个彩色两两至少隔这么多度，否则会互相误读
SPACING_PROPS = ("padding", "margin", "gap", "row-gap", "column-gap")
SPACING_GRID = 8
LINE_HEIGHT_FLOOR = 1.4
BODY_LINE_HEIGHT_FLOOR = 1.5
BODY_FONT_HEAD = ("arial", "helvetica")
# 正文对比度 4.5:1，交互控件边界 3:1（WCAG 1.4.3 / 1.4.11）。
TEXT_CONTRAST_FLOOR = 4.5
BOUNDARY_CONTRAST_FLOOR = 3.0

SURFACE_TOKENS = ("--bg", "--surface", "--surface-2")
FOREGROUND_TOKENS = ("--text", "--muted", "--act", "--pass", "--fail")


def theme_blocks(rules):
    """把 :root 块按主题分组。

    暗色是默认的那个 :root，浅色是 @media 里的覆盖；两者 token 名相同，
    所以按出现顺序取，第一个是暗色，其余每个都是一套完整覆盖。
    """
    blocks = []
    base = {}
    for rule in rules:
        if not rule.is_root:
            continue
        values = {name: value for name, value in rule.declarations()
                  if name.startswith("--")}
        if not blocks:
            base = values
            blocks.append(("dark", dict(values)))
        else:
            merged = dict(base)
            merged.update(values)
            blocks.append(("light", merged))
    return blocks


def _token_rgb(values, name):
    found = colors_in(values.get(name, ""))
    return found[0] if found else None


def check_tokens():
    report = Report("tokens")
    rules = parse_css(THEME_CSS)
    blocks = theme_blocks(rules)
    tokens = collect_tokens(rules)

    _check_hues(report, rules, blocks)
    _check_font_stack(report, rules, tokens)
    _check_line_heights(report, rules, tokens)
    _check_spacing_grid(report, rules, tokens)
    _check_color_literals(report, rules)
    _check_contrast(report, blocks)
    return report


def _check_hues(report, rules, blocks):
    """A1-1 彩色恰好三种。

    不做色相聚类——聚类要挑一个容差，而容差是可以被将来的人调松的。改成精确
    断言：每套主题里饱和度超过下限的 token 恰好是 --act / --pass / --fail，
    并且文件里出现的每个彩色字面量都等于其中之一。
    """
    problems = []
    per_theme = {}
    for theme, values in blocks:
        chromatic = []
        for name, raw in values.items():
            rgb = _token_rgb(values, name)
            if rgb and chroma(rgb) > CHROMA_FLOOR:
                chromatic.append(name)
        per_theme[theme] = sorted(chromatic)
        if sorted(chromatic) != sorted(CHROMATIC_TOKENS):
            problems.append("%s 主题的彩色 token 是 %s" %
                            (theme, "、".join(sorted(chromatic)) or "（无）"))

    allowed = set()
    for _theme, values in blocks:
        for name in CHROMATIC_TOKENS:
            rgb = _token_rgb(values, name)
            if rgb:
                allowed.add(rgb)
    for rule in rules:
        if rule.is_root:
            continue
        for prop, value in rule.declarations():
            for rgb in colors_in(value):
                if chroma(rgb) > CHROMA_FLOOR and rgb not in allowed:
                    problems.append("%s { %s } 用了三色之外的彩色 %s"
                                    % (rule.selector, prop, hex_of(rgb)))

    report.add("A1-1", "非中性色相恰好 3 种，且全文件彩色都取自这三个 token",
               {t: v for t, v in per_theme.items()}, list(CHROMATIC_TOKENS),
               not problems, problems)

    # act 与 fail 都是暖色，靠得太近就等于没有区分；把间距也钉死。
    gaps = []
    ok = True
    for theme, values in blocks:
        hues = {}
        for name in CHROMATIC_TOKENS:
            rgb = _token_rgb(values, name)
            if rgb:
                hues[name] = rgb_to_hsl(rgb)[0]
        names = sorted(hues)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                delta = abs(hues[names[i]] - hues[names[j]]) % 360
                delta = min(delta, 360 - delta)
                gaps.append("%s %s↔%s = %.1f°"
                            % (theme, names[i], names[j], delta))
                if delta < HUE_SEPARATION_FLOOR:
                    ok = False
    report.add("A1-1b", "三种彩色两两色相间距不小于 %.0f°" % HUE_SEPARATION_FLOOR,
               "见明细", "≥ %.0f°" % HUE_SEPARATION_FLOOR, ok, gaps)


def _check_font_stack(report, rules, tokens):
    """A1-2 正文用系统标准无衬线体，等宽字体只留一个使用点。"""
    body_stack = None
    mono_users = []
    for rule in rules:
        for prop, value in rule.declarations():
            if prop != "font-family":
                continue
            if rule.selector == "body":
                body_stack = resolve_vars(value, tokens)
            elif not rule.is_root and "var(--font-mono)" not in value \
                    and "var(--font-body)" not in value:
                mono_users.append("%s { font-family: %s }"
                                  % (rule.selector, value))
    head = []
    if body_stack:
        head = [p.strip().strip('"\'').lower()
                for p in body_stack.split(",")][:2]
    report.expect_equal("A1-2", "正文字体栈以标准无衬线体开头",
                        head, list(BODY_FONT_HEAD))
    report.add("A1-2b", "字体只由 --font-body / --font-mono 两个 token 提供",
               len(mono_users), 0, not mono_users, mono_users)


def _check_line_heights(report, rules, tokens):
    """A1-3 行高下限。"""
    values = []
    problems = []
    body_lh = None
    for rule in rules:
        for prop, value in rule.declarations():
            if prop != "line-height":
                continue
            value = resolve_vars(value, tokens)
            for number in re.findall(r"(?<![\w-])(\d*\.?\d+)(?![\w%.])", value):
                number = float(number)
                values.append(number)
                if number < LINE_HEIGHT_FLOOR:
                    problems.append("%s { line-height: %s }"
                                    % (rule.selector, value))
                if rule.selector == "body" or rule.is_root and "lh-body" in prop:
                    body_lh = number
    # body 的 line-height 走 var(--lh-body)，实际值在 token 里。
    for rule in rules:
        if not rule.is_root:
            continue
        for prop, value in rule.declarations():
            if prop == "--lh-body":
                body_lh = float(value.strip())

    report.add("A1-3", "全部 line-height 不低于 %.1f" % LINE_HEIGHT_FLOOR,
               min(values) if values else None,
               "≥ %.1f" % LINE_HEIGHT_FLOOR, not problems, problems)
    report.expect_at_least("A1-3b", "正文 line-height 不低于 %.1f"
                           % BODY_LINE_HEIGHT_FLOOR, body_lh,
                           BODY_LINE_HEIGHT_FLOOR)


def _check_spacing_grid(report, rules, tokens):
    """A1-4 间距的 px 值落在 8px 栅格上。

    只约束 px：markdown 正文里的 em 间距跟随字号缩放，是文本流的行距而不是
    组件内边距。为了不让这条豁免变成暗门，把 em 间距的条数一并报出来。
    """
    total = 0
    offenders = []
    em_count = 0
    for rule in rules:
        for prop, value in rule.declarations():
            base = prop.split("-")[0] if prop.startswith(("padding", "margin")) \
                else prop
            if base not in SPACING_PROPS and prop not in SPACING_PROPS:
                continue
            if rule.is_root:
                continue
            if re.search(r"\d\s*e[mx]\b", value):
                em_count += 1
            value = resolve_vars(value, tokens)
            for px in re.findall(r"(-?\d+)px", value):
                total += 1
                if int(px) % SPACING_GRID != 0:
                    offenders.append("%s { %s: %s }"
                                     % (rule.selector, prop, value.strip()))
                    break
    report.add("A1-4",
               "padding/margin/gap 的 px 值都是 %d 的倍数（em 间距属文本流，"
               "本条不约束，共 %d 处）" % (SPACING_GRID, em_count),
               "%d / %d 条违规" % (len(offenders), total),
               "0 / %d" % total, not offenders, offenders)


def _check_color_literals(report, rules):
    """A1-5 颜色字面量只允许出现在 token 定义块。"""
    offenders = []
    for rule in rules:
        if rule.is_root:
            continue
        for prop, value in rule.declarations():
            if colors_in(value):
                offenders.append("%s { %s: %s }"
                                 % (rule.selector, prop, value.strip()))
    report.add("A1-5", ":root 之外没有颜色字面量", len(offenders), 0,
               not offenders, offenders)


def _check_contrast(report, blocks):
    """A1-6 对比度下限。"""
    problems = []
    measured = []
    for theme, values in blocks:
        for fg_name in FOREGROUND_TOKENS:
            fg = _token_rgb(values, fg_name)
            if not fg:
                problems.append("%s 主题缺少 %s" % (theme, fg_name))
                continue
            for bg_name in SURFACE_TOKENS:
                bg = _token_rgb(values, bg_name)
                if not bg:
                    continue
                ratio = contrast_ratio(fg, bg)
                measured.append("%s %s/%s = %.2f"
                                % (theme, fg_name, bg_name, ratio))
                if ratio < TEXT_CONTRAST_FLOOR:
                    problems.append("%s %s 在 %s 上只有 %.2f:1"
                                    % (theme, fg_name, bg_name, ratio))
        strong = _token_rgb(values, "--border-strong")
        for bg_name in ("--surface", "--surface-2"):
            bg = _token_rgb(values, bg_name)
            if strong and bg:
                ratio = contrast_ratio(strong, bg)
                measured.append("%s --border-strong/%s = %.2f"
                                % (theme, bg_name, ratio))
                if ratio < BOUNDARY_CONTRAST_FLOOR:
                    problems.append("%s 控件边界在 %s 上只有 %.2f:1"
                                    % (theme, bg_name, ratio))
    report.add("A1-6",
               "正文组合 ≥ %.1f:1，交互控件边界 ≥ %.1f:1"
               % (TEXT_CONTRAST_FLOOR, BOUNDARY_CONTRAST_FLOOR),
               "%d 组已测，%d 组不达标" % (len(measured), len(problems)),
               "0 组不达标", not problems, problems or measured)


# --------------------------------------------------------------------------
# 版式与组件
# --------------------------------------------------------------------------
#
# tokens 组管的是「变量本身合不合规」：三种色、Arial 打头、行高 1.4、8px 栅格。
# 那六条全部通过的页面依然可以很难看，因为决定观感的是别的东西：字号有没有层级、
# 某一种颜色是不是被到处乱用、中文标题有没有被强行加字距。下面这几条就是把那些
# 「看着乱」换成能算的数。
#
# 它们的共同点是都能失败——每一条在写下来的时候都是红的，是先有实测的违规才有的
# 条款，不是先有条款再去凑。

FONT_SCALE_CEILING = 6        # 字号档位数上限：再多就等于没有层级
FONT_SCALE_MIN_PX = 12.0      # 最小档位：11px 的中文在深色底上已经开始糊
FONT_SCALE_MIN_RATIO = 1.125  # 相邻档位比：差一两个 px 的两档人眼分不出，等于白设
CHROMATIC_TEXT_SHARE = 0.40   # 着彩色的文字规则占全部文字色规则的比例上限
MEASURE_RANGE = (45.0, 90.0)  # 正文每行字符数的常见可读区间
_EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF️]")


def _font_size_tokens(tokens):
    out = {}
    for name, value in tokens.items():
        if not name.startswith("--fs-"):
            continue
        m = re.match(r"^\s*(\d*\.?\d+)px\s*$", value)
        if m:
            out[name] = float(m.group(1))
    return out


def _px(value):
    m = re.match(r"^\s*(\d*\.?\d+)px\s*$", value)
    return float(m.group(1)) if m else None


def check_layout():
    report = Report("layout")
    rules = parse_css(THEME_CSS)
    tokens = collect_tokens(rules)

    _check_font_scale(report, rules, tokens)
    _check_accent_balance(report, rules)
    _check_cjk_letter_spacing(report, rules)
    _check_strikethrough(report, rules)
    _check_emoji(report)
    _check_inline_px(report)
    _check_measure(report, rules, tokens)
    return report


def _check_font_scale(report, rules, tokens):
    """A5-1 字号只能取自一条有真实层级的阶梯。

    改造前 theme.css 里有 8 个互不相干的字号（11/12/13/14/15/16/17/22），其中
    11↔12↔13↔14 四档彼此相差不到 10%——写了四档，看上去只有一档。
    """
    scale = _font_size_tokens(tokens)
    sizes = sorted(scale.values())

    offenders = []
    for rule in rules:
        if rule.is_root:
            continue
        for prop, value in rule.declarations():
            if prop != "font-size":
                continue
            resolved = _px(resolve_vars(value, tokens))
            if resolved is None or resolved not in sizes:
                offenders.append("%s { font-size: %s }"
                                 % (rule.selector, value.strip()))
    report.add("A5-1", "每个 font-size 都取自 --fs-* 阶梯",
               "%d 条不在阶梯上 / 共 %d 档" % (len(offenders), len(sizes)),
               "0 条不在阶梯上", not offenders and bool(sizes), offenders)

    problems = []
    # 没有阶梯时这条必须报红。少了这句，`min()`/`zip()` 在空列表上一条都不检查，
    # 于是「一个 --fs-* 都没定义」会被报成通过——空转的绿灯比红灯更坏。
    if not sizes:
        problems.append("没有定义任何 --fs-* token，这条断言无从计算")
    if len(sizes) > FONT_SCALE_CEILING:
        problems.append("阶梯有 %d 档，超过 %d 档" % (len(sizes), FONT_SCALE_CEILING))
    if sizes and sizes[0] < FONT_SCALE_MIN_PX:
        problems.append("最小档 %.0fpx 低于 %.0fpx" % (sizes[0], FONT_SCALE_MIN_PX))
    ratios = []
    for a, b in zip(sizes, sizes[1:]):
        ratios.append("%.0f→%.0f = %.3f" % (a, b, b / a))
        if b / a < FONT_SCALE_MIN_RATIO:
            problems.append("相邻档 %.0fpx 与 %.0fpx 只差 %.1f%%"
                            % (a, b, (b / a - 1) * 100))
    report.add("A5-1b",
               "阶梯不超过 %d 档、最小档不低于 %.0fpx、相邻档比不低于 %.3f"
               % (FONT_SCALE_CEILING, FONT_SCALE_MIN_PX, FONT_SCALE_MIN_RATIO),
               "%d 档：%s" % (len(sizes), "/".join("%.0f" % s for s in sizes)),
               "无违规", not problems, problems or ratios)


def _chromatic_in(value):
    return [name for name in CHROMATIC_TOKENS
            if re.search(r"var\(\s*%s\s*[,)]" % re.escape(name), value)]


_HEADING_RE = re.compile(r"(^|[\s>+~])h[1-6]\b|heading|-title\b")


def _check_accent_balance(report, rules):
    """A5-2 标题不着彩色。

    找这条判据绕了两圈，两次都失败，记在这里免得下次再绕：先按「彩色被多少条
    规则引用」数，得到 act 18 / pass 12 / fail 10，比值 1.8，很均衡；再按「着
    彩色的 color: 声明占比」数，得到 33%，也不高。可页面一眼看过去就是橙的。

    数错了对象。规则条数看不见**出现频次**：`.md h2 { color: var(--act) }` 只是
    一条规则，却让每篇文档的每个二级标题都变橙；`ul.tasks li.heading` 一条规则
    对应满屏的任务分组。真正让整页发橙的是彩色落在了**版面骨架**上——标题是读者
    扫视时的落点，把落点全部染色，等于宣布整页都需要注意，也就等于没有重点。

    所以这条只管标题：标题靠字号与字重区分层级，颜色留给状态。
    """
    offenders = []
    for rule in rules:
        if rule.is_root:
            continue
        for part in rule.selector.split(","):
            part = part.strip()
            if not _HEADING_RE.search(part):
                continue
            for prop, value in rule.declarations():
                if prop != "color":
                    continue
                hits = _chromatic_in(value)
                if hits:
                    offenders.append("%s { color: %s }" % (part, value.strip()))
    report.add("A5-2", "标题（h1–h6 / *heading* / *-title）不着彩色",
               len(offenders), 0, not offenders, offenders)

    # 正文里的文字流不着彩色。判据用选择器形态区分，不用白名单：`.md h2`、
    # `.md p` 这样的元素选择器是文本流，必须中性；`.md .cbx` 这样的类选择器是
    # 打在特定标记上的状态符号，是少数几个字符，允许带色。`a` 是交互，也允许。
    prose = []
    for rule in rules:
        for part in rule.selector.split(","):
            part = part.strip()
            m = re.match(r"^\.md\s+([a-z][\w]*)\b$", part)
            if not m or m.group(1) == "a":
                continue
            body = " ".join("%s:%s" % (p, v) for p, v in rule.declarations())
            hits = _chromatic_in(body)
            if hits:
                prose.append("%s 引用了 %s" % (part, "、".join(hits)))
    report.add("A5-2b", "markdown 文本流（元素选择器）不着彩色，链接与状态标记除外",
               len(prose), 0, not prose, prose)

    # 这条从写下来那一刻就是绿的（33%），不是它发现了什么，是防回归：上面两条
    # 管的是「哪里不能上色」，这条管总量，免得有人把彩色改挂到别的选择器上。
    chromatic, total = [], 0
    for rule in rules:
        if rule.is_root:
            continue
        for prop, value in rule.declarations():
            if prop != "color":
                continue
            total += 1
            if _chromatic_in(value):
                chromatic.append("%s { color: %s }"
                                 % (rule.selector, value.strip()))
    share = (len(chromatic) / total) if total else 0.0
    report.add("A5-2c", "着彩色的文字规则不超过全部文字色规则的 %.0f%%（防回归）"
               % (CHROMATIC_TEXT_SHARE * 100),
               "%.0f%%（%d / %d 条）" % (share * 100, len(chromatic), total),
               "≤ %.0f%%" % (CHROMATIC_TEXT_SHARE * 100),
               total > 0 and share <= CHROMATIC_TEXT_SHARE, chromatic)


def _check_cjk_letter_spacing(report, rules):
    """A5-3 字距与大写化只允许用在全 ASCII 的等宽文本上。

    改造前侧栏分组标题「变更」「证据」和区块标题都带 text-transform: uppercase
    加 letter-spacing: .05em。中文没有大写，uppercase 什么也没做；letter-spacing
    则把本来就靠字面间距成词的汉字撑散。判据用「同一规则里是否声明了等宽字体」
    做代理：走等宽的是 ID、路径、步骤号，那些确实全是 ASCII。
    """
    offenders = []
    for rule in rules:
        if rule.is_root:
            continue
        decls = dict(rule.declarations())
        spaced = "letter-spacing" in decls and decls["letter-spacing"].strip() \
            not in ("0", "normal", "0px", "0em")
        upper = decls.get("text-transform", "").strip() == "uppercase"
        if not (spaced or upper):
            continue
        if "var(--font-mono)" in decls.get("font-family", ""):
            continue
        offenders.append("%s { %s }" % (rule.selector, "; ".join(
            "%s: %s" % (k, decls[k]) for k in ("letter-spacing", "text-transform")
            if k in decls)))
    report.add("A5-3", "letter-spacing / text-transform 只用在等宽（全 ASCII）文本上",
               len(offenders), 0, not offenders, offenders)


def _check_strikethrough(report, rules):
    """A5-4 不用删除线表示完成。

    一行中文上拉一条贯穿线会把字形切成两半，而 tasks.md 有 40 条，整屏都是。
    完成态本来就有复选框和降饱和的文字色两重信号，删除线只是在削可读性。
    """
    offenders = []
    for rule in rules:
        for prop, value in rule.declarations():
            if "line-through" in value:
                offenders.append("%s { %s: %s }" % (rule.selector, prop, value.strip()))
    report.add("A5-4", "不用 line-through 表示完成", len(offenders), 0,
               not offenders, offenders)


def _check_emoji(report):
    """A5-5 界面里不出现 emoji。

    emoji 由系统字体渲染，字形宽度、基线、着色都不受 theme.css 控制，混在一套
    定好了字号与行高的排版里就是几个大小不一的彩色色块。🗂 📊 📋 🕒 五个图标
    在改造前分别出现在标题、概览页、折叠条与检查点上。
    """
    offenders = []
    for path in (os.path.join(DASHBOARD_DIR, "index.html"), THEME_CSS,
                 APP_JS, GRAPH_JS):
        text = _read(path)
        for m in _EMOJI_RE.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            offenders.append("%s:%d 出现 %r"
                             % (os.path.basename(path), line, m.group(0)))
    report.add("A5-5", "前端源文件里没有 emoji 码点", len(offenders), 0,
               not offenders, offenders)


def _check_inline_px(report):
    """A5-7 前端 JS 里的内联样式不得带 px。

    这是上面几条的一个漏洞：契约脚本解析的是 theme.css，而 `el("div", {style:
    "gap:6px"})` 写在 app.js 里，8px 栅格断言根本看不见它——改造前就有三处这样
    的内联 px（gap:6px、margin-top:14px、margin-bottom:8px），其中两处不合栅格，
    A1-4 却一直报绿。尺寸一旦跑进 JS 就脱离了设计变量，所以这里直接禁掉。

    按数据算的样式（进度条宽度用 %、任务缩进用 em）不受影响：它们本来就不该是
    常量。
    """
    offenders = []
    for path in (APP_JS, GRAPH_JS):
        text = _read(path)
        for m in re.finditer(r"""(style\s*:\s*["'][^"']*|\.style\.[\w]+\s*=[^;\n]*)""",
                             text):
            if re.search(r"\d\s*px", m.group(0)):
                line = text.count("\n", 0, m.start()) + 1
                offenders.append("%s:%d %s"
                                 % (os.path.basename(path), line,
                                    m.group(0).strip()[:60]))
    report.add("A5-7", "前端 JS 的内联样式里没有 px 字面量", len(offenders), 0,
               not offenders, offenders)


def _check_measure(report, rules, tokens):
    """A5-6 正文每行字符数落在可读区间。

    这一条改造前就是通过的，写下来是为了把 max-width 和 body 字号绑在一起：
    调大字号却不动栏宽会把行变短，调宽栏宽却不动字号会把行拉长，两个数单独看
    都没问题，只有比值有意义。
    """
    width = size = None
    for rule in rules:
        for prop, value in rule.declarations():
            if rule.selector == ".content-inner" and prop == "max-width":
                width = _px(resolve_vars(value, tokens))
            if rule.selector == "body" and prop == "font-size":
                size = _px(resolve_vars(value, tokens))
    measure = (width / size) if width and size else None
    lo, hi = MEASURE_RANGE
    report.add("A5-6", "正文每行字符数在 %.0f–%.0f 之间" % (lo, hi),
               "%.1f 字符（栏宽 %s / 字号 %s）"
               % (measure or 0, width, size),
               "%.0f–%.0f" % (lo, hi),
               measure is not None and lo <= measure <= hi)


CLICK_DEPTH_CEILING = 3
NAV_DEPTH_CEILING = 3
LIBRARY_DIRS = ("quality", "knowledge", "adr", "architecture")


def _state():
    """取与 `harness status` / 看板同一份状态投影，不新写一份。"""
    import harness_state
    return harness_state.build_state()


def _walk_nav(nodes, depth=1, ancestors=()):
    for node in nodes or []:
        yield node, depth, ancestors
        for item in _walk_nav(node.get("children"), depth + 1,
                              ancestors + (node,)):
            yield item


def click_depth(node, ancestors):
    """从首屏状态数到这个节点要点几下。

    每个没有默认展开的祖先要点一次展开，最后再点节点自己。
    """
    return sum(1 for a in ancestors if not a.get("initial_expanded")) + 1


def check_nav():
    report = Report("nav")
    state = _state()
    tree = state.get("nav_tree") or []
    if not tree:
        report.add("A2-0", "/api/state 提供 nav_tree", "缺失", "非空", False)
        return report

    leaves = [(n, d, a) for n, d, a in _walk_nav(tree) if not n.get("children")]

    # A2-1 任意目标的点击深度
    worst = []
    deepest = 0
    for node, _depth, ancestors in leaves:
        clicks = click_depth(node, ancestors)
        deepest = max(deepest, clicks)
        if clicks > CLICK_DEPTH_CEILING:
            worst.append("%s 需要 %d 次点击" % (node["key"], clicks))
    report.add("A2-1", "任意叶子从首屏起的导航点击次数不超过 %d"
               % CLICK_DEPTH_CEILING, deepest,
               "≤ %d" % CLICK_DEPTH_CEILING, not worst, worst)

    # A2-2 树深与计数
    problems = []
    max_depth = 0
    for node, depth, _ancestors in _walk_nav(tree):
        max_depth = max(max_depth, depth)
        if depth > NAV_DEPTH_CEILING:
            problems.append("%s 在第 %d 层" % (node["key"], depth))
        if node.get("children") and node.get("count") is None:
            problems.append("分组 %s 没有条目计数" % node["key"])
    report.add("A2-2", "树深不超过 %d，且每个分组都带条目计数" % NAV_DEPTH_CEILING,
               max_depth, "≤ %d" % NAV_DEPTH_CEILING, not problems, problems)

    # A2-3 覆盖恰好一次
    seen_changes, seen_docs = {}, {}
    for node, _depth, _ancestors in _walk_nav(tree):
        if node.get("kind") == "change":
            seen_changes[node["change"]] = seen_changes.get(node["change"], 0) + 1
        elif node.get("kind") == "doc":
            path = node["doc_path"]
            seen_docs[path] = seen_docs.get(path, 0) + 1

    # 期望集合从磁盘算，不从 state["library"] 算。拿投影去比投影，任何在
    # 列举阶段就被丢掉的文档都不会被发现——docs/quality/pitfalls/ 的三篇正是
    # 这样长期不在看板里的。
    expected_changes = {c["id"] for c in state["changes"]}
    expected_docs = set()
    for key in LIBRARY_DIRS:
        base = os.path.join(ROOT, "docs", key)
        for cur, _dirs, files in os.walk(base):
            for name in files:
                if name.endswith(".md"):
                    expected_docs.add(os.path.relpath(
                        os.path.join(cur, name), ROOT).replace("\\", "/"))

    problems = []
    for missing in sorted(expected_changes - set(seen_changes)):
        problems.append("change %s 不在导航树里" % missing)
    for missing in sorted(expected_docs - set(seen_docs)):
        problems.append("文档 %s 不在导航树里" % missing)
    for key, count in sorted(seen_changes.items()) + sorted(seen_docs.items()):
        if count > 1:
            problems.append("%s 在导航树里出现了 %d 次" % (key, count))
    report.add("A2-3", "每个 change 与每篇长期文档在树中恰好出现一次",
               "%d change + %d 文档" % (len(seen_changes), len(seen_docs)),
               "%d change + %d 文档"
               % (len(expected_changes), len(expected_docs)),
               not problems, problems)

    # A2-4 首屏展开集合
    problems = []
    for node, depth, _ancestors in _walk_nav(tree):
        if not node.get("children"):
            continue
        should = depth == 1
        if bool(node.get("initial_expanded")) != should:
            problems.append("%s（第 %d 层）首屏 %s"
                            % (node["key"], depth,
                               "展开" if node.get("initial_expanded") else "收起"))
    expanded = [n["key"] for n, d, _a in _walk_nav(tree)
                if n.get("initial_expanded")]
    report.add("A2-4", "一级分组首屏展开，二级分组首屏收起",
               expanded, "全部一级分组", not problems, problems)

    return report


def _function_source(text, name):
    """从 JS 里截出一个函数体，按花括号配平。"""
    start = text.find("function %s(" % name)
    if start < 0:
        return ""
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]


def check_graphs(flow=True, relations=True):
    report = Report("graphs")
    if flow:
        _check_flow(report)
    if relations:
        _check_relations(report)
    return report


def _check_relations(report):
    import ast

    import harness_state
    sys.path.insert(0, DASHBOARD_DIR)
    import server  # noqa: E402

    state = _state()
    graphs = dict(state.get("graphs") or {})
    graphs["data_flow"] = server.data_flow_graph()

    # A4-1 依赖图的边就是 change_context 里声明的依赖，一条不多一条不少。
    contexts = state["current"].get("change_context") or {}
    known = {c["id"] for c in state["changes"]}
    expected = set()
    for change_id, context in contexts.items():
        if change_id not in known or not isinstance(context, dict):
            continue
        for target in context.get("depends_on") or []:
            if target in known:
                expected.add((target, change_id))
    actual = {(e["from"], e["to"]) for e in graphs["dependency"]["edges"]}
    report.expect_equal("A4-1", "归档依赖图的边集等于 change_context 声明的依赖",
                        sorted(actual), sorted(expected),
                        ["多出 %s→%s" % e for e in sorted(actual - expected)] +
                        ["缺少 %s→%s" % e for e in sorted(expected - actual)])

    # A4-2 新增 route 却没登记 DATA_FLOW 时必须失败——这条是防漂移的那道门槛。
    registered = server.registered_routes()
    declared = {entry["route"] for entry in server.DATA_FLOW}
    drawn = {n["label"] for n in graphs["data_flow"]["nodes"]
             if n["kind"] == "route"}
    problems = ["route %s 已注册但没有登记 DATA_FLOW" % r
                for r in sorted(registered - declared)]
    problems += ["DATA_FLOW 登记了不存在的 route %s" % r
                 for r in sorted(declared - registered)]
    problems += ["route %s 没有画进数据流图" % r
                 for r in sorted(declared - drawn)]
    report.expect_equal("A4-2", "数据流图覆盖 server.py 已注册的全部 route",
                        sorted(drawn), sorted(registered), problems)

    # A4-3 模块图的边就是 import 关系。
    scripts_dir = os.path.join(ROOT, ".harness", "scripts")
    sources = {name[:-3]: os.path.join(scripts_dir, name)
               for name in sorted(os.listdir(scripts_dir))
               if name.endswith(".py")}
    sources["server"] = os.path.join(DASHBOARD_DIR, "server.py")
    expected = set()
    for module, path in sources.items():
        try:
            tree = ast.parse(_read(path))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for target in names:
                if target in sources and target != module:
                    expected.add((module, target))
    actual = {(e["from"], e["to"]) for e in graphs["modules"]["edges"]}
    report.expect_equal("A4-3", "模块结构图的边集等于 ast 解析出的 import 关系",
                        sorted(actual), sorted(expected),
                        ["多出 %s→%s" % e for e in sorted(actual - expected)] +
                        ["缺少 %s→%s" % e for e in sorted(expected - actual)])

    # A4-4 单向箭头：渲染器只挂 marker-end。
    graph_js = _read(GRAPH_JS)
    problems = []
    if "marker-start" in graph_js:
        problems.append("graph.js 出现了 marker-start，箭头会变双向")
    if graph_js.count('"marker-end"') < 1:
        problems.append("graph.js 没有给边挂终点箭头")
    report.add("A4-4", "每条边只有终点箭头，方向可直读",
               "%d 个问题" % len(problems), 0, not problems, problems)

    # A4-5 图注不依赖图例。
    problems = []
    for key, graph in sorted(graphs.items()):
        caption = (graph.get("caption") or "").strip()
        if len(caption) < 20:
            problems.append("%s 的图注太短（%d 字）" % (key, len(caption)))
        elif "箭头" not in caption:
            problems.append("%s 的图注没有说明箭头的含义" % key)
    for change in state["changes"]:
        caption = (change["verification_flow"].get("caption") or "").strip()
        if len(caption) < 20 or "箭头" not in caption:
            problems.append("%s 的流程图图注没有说明箭头含义" % change["id"])
            break
    report.add("A4-5", "每张图都有说明箭头指向含义的图注，不依赖图例",
               "%d 张图，%d 张不合格" % (len(graphs) + 1, len(problems)), 0,
               not problems, problems)

    # A4-6 节点自解释：标签之外还要有一句说明，不能只有裸标识符。
    problems = []
    checked = 0
    for key, graph in sorted(graphs.items()):
        for node in graph["nodes"]:
            checked += 1
            if not str(node.get("label") or "").strip():
                problems.append("%s 有节点没有标签" % key)
            if not str(node.get("detail") or "").strip():
                problems.append("%s 的节点 %s 只有裸标识符，没有说明"
                                % (key, node.get("label")))
    report.add("A4-6", "每个节点都带一句说明，不是裸标识符",
               "%d 个节点，%d 个不合格" % (checked, len(problems)), 0,
               not problems, problems)


def _check_flow(report):
    state = _state()

    # A3-1 图上的步骤节点覆盖全部步骤。
    problems = []
    total_steps = total_nodes = 0
    for change in state["changes"]:
        flow = change.get("verification_flow") or {}
        step_nodes = [n for n in flow.get("nodes") or []
                      if n.get("kind") == "step"]
        steps = change.get("steps") or []
        total_steps += len(steps)
        total_nodes += len(step_nodes)
        if len(step_nodes) != len(steps):
            problems.append("%s：%d 个步骤但图上有 %d 个节点"
                            % (change["id"], len(steps), len(step_nodes)))
        missing = {str(s.get("id")) for s in steps} - {
            n["label"] for n in step_nodes}
        for step_id in sorted(missing):
            problems.append("%s 的步骤 %s 不在图上" % (change["id"], step_id))
    report.expect_equal("A3-1", "流程图的步骤节点数等于 verification.json 的步骤数",
                        total_nodes, total_steps, problems)

    # A3-2 / A3-3 是渲染代码的结构性质。这里做的是**源码级**断言，不是对渲染
    # 后 DOM 的断言——没有浏览器就无法查 DOM，而为了查 DOM 引一个浏览器会破坏
    # 「契约脚本零依赖」。这一点在描述里写明，不要当成 DOM 已验证。
    app = _read(APP_JS)
    fn = _function_source(app, "renderFlowFigure")

    checks = {
        "从 ch.steps 逐条生成 <li>": "ch.steps.forEach" in fn,
        "列表是 ol.flow-steps": 'el("ol", { class: "flow-steps" })' in fn,
        "条目含步骤编号": "s.id" in fn,
        "条目含状态": "STATUS_LABEL(s.status)" in fn,
        "条目含角色": "ROLE_LABEL(s.role)" in fn,
        "条目含通过判据": "s.pass_when" in fn,
    }
    failed = [name for name, ok in checks.items() if not ok]
    report.add("A3-2",
               "文字编号摘要由 ch.steps 逐条生成，每条含编号、状态、角色、通过判据"
               "（源码级断言）",
               "%d / %d 项成立" % (len(checks) - len(failed), len(checks)),
               "全部成立", not failed, failed)

    ol_append = fn.find("fig.appendChild(ol)")
    try_at = fn.find("try {")
    render_at = fn.find("HarnessGraph.render")
    problems = []
    if ol_append < 0:
        problems.append("找不到把 <ol> 挂进 <figure> 的地方")
    if try_at < 0 or render_at < 0:
        problems.append("找不到被 try 包住的图形渲染")
    if ol_append >= 0 and try_at >= 0 and ol_append > try_at:
        problems.append("<ol> 在 try 块之后才进 DOM；图形抛异常时它会一起消失")
    if try_at >= 0 and render_at >= 0 and render_at < try_at:
        problems.append("图形渲染在 try 之外")
    report.add("A3-3",
               "<ol> 先无条件进 DOM，图形渲染整体在 try 内（源码级断言）",
               "ol@%d try@%d render@%d" % (ol_append, try_at, render_at),
               "ol < try ≤ render", not problems, problems)

    # A3-4 图必须能被读出来。
    graph = _read(GRAPH_JS)
    problems = []
    if '"aria-label": options.title' not in graph:
        problems.append("<svg> 没有 aria-label")
    if 'svgEl("title"' not in graph:
        problems.append("<svg> 没有 <title>")
    if "marker-start" in graph:
        problems.append("图形渲染器用了 marker-start，箭头会变双向")
    if '"marker-end": "url(#g-arrow)"' not in graph:
        problems.append("边没有终点箭头")
    report.add("A3-4", "每个 <svg> 有 <title> 与 aria-label，边只有终点箭头",
               "%d 个问题" % len(problems), 0, not problems, problems)


# --------------------------------------------------------------------------
# 证据分类与图片内联
# --------------------------------------------------------------------------

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp")


def _disk_evidence():
    """直接走磁盘列出证据。

    期望集合必须从原始事实算，不能从被测的投影算——拿投影比投影，投影自身漏掉
    的东西两边都没有，于是永远相等。这条教训在导航覆盖断言上已经付过一次学费。
    """
    root = os.path.join(ROOT, ".harness", "evidence")
    found = set()
    for cur, _dirs, files in os.walk(root):
        for name in files:
            if name == "README.md":
                continue
            found.add(os.path.relpath(os.path.join(cur, name),
                                      ROOT).replace("\\", "/"))
    return found


def check_evidence():
    report = Report("evidence")
    import harness_state
    index = harness_state.build_evidence_index()
    items = index["items"]

    # B1-1 覆盖：投影出的集合必须与磁盘上的完全相同。
    disk = _disk_evidence()
    projected = {it["path"] for it in items}
    missing = sorted(disk - projected)
    extra = sorted(projected - disk)
    report.add("B1-1", "证据投影覆盖磁盘上的每一个文件，且不多出",
               "投影 %d / 磁盘 %d" % (len(projected), len(disk)),
               "两者相等且非空",
               bool(disk) and not missing and not extra,
               ["缺: " + p for p in missing[:10]] +
               ["多: " + p for p in extra[:10]])

    # B1-2 分类是全函数：没有空值，没有 unclassified。
    unclassified = [it["path"] for it in items
                    if not it["kind"] or it["kind"] == "unclassified"
                    or not it["source"] or not it["date"]]
    report.add("B1-2", "每份证据都有非空的 kind / source / date，且无 unclassified",
               "%d / %d 项缺分类" % (len(unclassified), len(items)),
               "0 项缺分类", bool(items) and not unclassified, unclassified[:10])

    # B1-3 两种布局都在。历史平铺那批只要被漏掉就会整批从筛选里消失。
    sources = {it["source"] for it in items}
    flat = [it for it in items if it["source"] == harness_state.LEGACY_SOURCE]
    nested = [it for it in items if it["source"] != harness_state.LEGACY_SOURCE]
    report.add("B1-3", "平铺与子目录两种证据布局都被列举",
               "legacy-flat %d 份 / 子目录 %d 份（%d 个来源）"
               % (len(flat), len(nested), len(sources)),
               "两者都不为 0", bool(flat) and bool(nested))

    # B1-4 单条件筛选之所以成立，靠的是每个维度把全集划成一个**划分**：
    # 每份证据恰好落进该维度的一个取值里。满足这条，「按一个条件筛一次就得到
    # 目标集合」才是真的；不满足（某份证据落进两个取值，或一个都不落）就会
    # 出现怎么筛都找不到、或筛出来重复的情况。
    #
    # 这里刻意不写成「筛选结果 == 全量过滤结果」——那两边会是同一个表达式，
    # 是一条永远为真的断言。划分性质是能被数据违反的。
    dims = {
        "kind": lambda it: it["kind"],
        "source": lambda it: it["source"],
        "month": lambda it: (it["date"] or "")[:7],
    }
    problems = []
    checked = 0
    for dim, of in sorted(dims.items()):
        buckets = {}
        for it in items:
            buckets.setdefault(of(it), set()).add(it["path"])
        checked += len(buckets)
        covered = set()
        for value, paths in buckets.items():
            if not value:
                problems.append("%s 有一个空取值，%d 份证据归不进任何选项"
                                % (dim, len(paths)))
            overlap = covered & paths
            if overlap:
                problems.append("%s=%s 与其他取值重复 %d 份"
                                % (dim, value, len(overlap)))
            covered |= paths
        if covered != {it["path"] for it in items}:
            problems.append("%s 的取值没有覆盖全部证据（少 %d 份）"
                            % (dim, len(items) - len(covered)))
    report.add("B1-4", "每个维度都把证据全集划成不重不漏的划分（单条件筛选的前提）",
               "%d 个取值已验，%d 处问题" % (checked, len(problems)),
               "0 处问题", checked > 0 and not problems, problems[:10])

    # B1-4b 前端筛选函数的形状：三个维度取交集，空值视为不筛。契约脚本不执行
    # JS，所以这条只能从源码断言——它比不上真的跑一遍，但比什么都不查强。
    app_src = _read(APP_JS)
    filt = re.search(r"function filterEvidence\(.*?\n\}", app_src, re.S)
    shape = []
    if not filt:
        shape.append("找不到 filterEvidence()")
    else:
        if "EVIDENCE_DIMS.every" not in filt.group(0):
            shape.append("筛选没有对全部维度取交集")
        if "!want" not in filt.group(0):
            shape.append("空条件没有被当作「不筛」")
    report.add("B1-4b", "前端筛选对三个维度取交集，空条件视为不筛",
               len(shape), 0, not shape, shape)

    # B1-5 筛选选项与实际取值双向对应：没有空选项，也没有未被覆盖的证据。
    option_problems = []
    for key, dim in (("kinds", "kind"), ("sources", "source")):
        options = {o["value"] for o in index[key]}
        actual = {it[dim] for it in items}
        if options != actual:
            option_problems.append("%s 选项 %s ≠ 实际取值 %s"
                                   % (key, sorted(options - actual),
                                      sorted(actual - options)))
        for opt in index[key]:
            if opt["count"] <= 0:
                option_problems.append("%s 的选项 %s 没有对应证据"
                                       % (key, opt["value"]))
    report.add("B1-5", "筛选选项与证据实际属性双向相等，无空选项",
               len(option_problems), 0, not option_problems, option_problems)

    # B1-6 图片端点：不起服务，直接验证读取路径与字节一致性。
    images = [it for it in items
              if os.path.splitext(it["path"])[1].lower() in IMAGE_EXTS]
    failures = []
    for it in images:
        try:
            body, ext = harness_state.read_evidence_bytes(it["path"])
        except Exception as exc:  # noqa: BLE001
            failures.append("%s 读取失败: %s" % (it["path"], exc))
            continue
        with open(os.path.join(ROOT, it["path"]), "rb") as fh:
            if body != fh.read():
                failures.append("%s 字节与磁盘不一致" % it["path"])
    report.add("B1-6", "每份图片证据都能按原始字节读出",
               "%d / %d 份通过" % (len(images) - len(failures), len(images)),
               "全部通过", bool(images) and not failures, failures[:10])

    # B1-7 越界必须被拒。这条是新增读文件入口的承重断言。
    refused = []
    for bad in ("../../etc/passwd", "%2e%2e%2f%2e%2e%2fetc%2fpasswd",
                "/etc/passwd", ".harness/scripts/harness_state.py",
                "docs/quality/scorecard.md", ""):
        try:
            harness_state.read_evidence_bytes(bad)
            refused.append("未拦住: %r" % bad)
        except (ValueError, FileNotFoundError):
            pass
    report.add("B1-7", "越界、编码穿越、非证据白名单路径全部被拒",
               len(refused), 0, not refused, refused)

    # B1-8 SVG 不得内联进 DOM。
    app = _read(APP_JS)
    inline = []
    if re.search(r"innerHTML\s*=\s*[^;]*evidence", app):
        inline.append("app.js 把证据内容写进了 innerHTML")
    if "evidence-file" in app and not re.search(
            r'el\("img"[^)]*evidenceUrl', app, re.S):
        inline.append("图片证据不是经 <img src> 载入的")
    report.add("B1-8", "图片证据只经 <img src> 载入，不进 innerHTML",
               len(inline), 0, not inline, inline)

    return report


# --------------------------------------------------------------------------
# 角色档案与确认自动填充
# --------------------------------------------------------------------------

def check_roles():
    report = Report("roles")
    import harness_roles
    import harness_state
    harness_roles.configure_root(ROOT)

    state = harness_roles.load()
    report.add("B2-1", "角色档案可读且 active_profile 有效",
               "%d 个档案，激活 %s" % (len(state["profiles"]),
                                      state["active_profile"]),
               "非空且激活项存在",
               bool(state["profiles"]) and any(
                   p["id"] == state["active_profile"] for p in state["profiles"]))

    # B2-2 档案结构里不存在可写入身份的字段。这是 C3 的结构性保证：不靠服务端
    # 记得过滤，靠档案里根本没有那个东西。
    identity_fields = {"evaluated_by", "agent", "model"}
    leaked = [f for f in identity_fields if f in harness_roles.PROFILE_FIELDS]
    for profile in state["profiles"]:
        leaked.extend("%s 含 %s" % (profile["id"], f)
                      for f in identity_fields if f in profile)
    report.add("B2-2", "角色档案不含任何可写入 evaluated_by 的字段",
               len(leaked), 0, not leaked, leaked)

    # B2-3 非法档案被拒且不落盘。
    rejected = []
    for bad, label in (
            ({"active_profile": "a",
              "profiles": [{"id": "a", "role": "wizard"}]}, "非法 role"),
            ({"active_profile": "a",
              "profiles": [{"id": "a", "role": "human"},
                           {"id": "a", "role": "human"}]}, "重复 id"),
            ({"active_profile": "nope",
              "profiles": [{"id": "a", "role": "human"}]}, "未知 active_profile"),
            ({"active_profile": "a",
              "profiles": [{"id": "a", "role": "human",
                            "evaluated_by": {"agent": "x"}}]}, "夹带身份字段")):
        try:
            harness_roles.validate(bad)
            rejected.append("未拦住: " + label)
        except harness_roles.RoleError:
            pass
    report.add("B2-3", "非法档案一律被拒（校验先于写入）",
               len(rejected), 0, not rejected, rejected)

    # B2-4 看板路径不得写 evaluated_by。从源码断言，而不是只靠一次运行。
    forge = []
    state_src = _read(os.path.join(ROOT, ".harness", "scripts",
                                   "harness_state.py"))
    server_src = _read(os.path.join(ROOT, ".harness", "dashboard", "server.py"))
    m = re.search(r"def update_verification_step\(.*?\n(?=\ndef |\Z)",
                  state_src, re.S)
    if not m:
        forge.append("找不到 update_verification_step")
    else:
        if re.search(r"\bagent\s*=", m.group(0)) or \
                re.search(r"\bmodel\s*=", m.group(0)):
            forge.append("update_verification_step 把 agent/model 传给了 set_step")
    if re.search(r'payload\.get\(\s*["\']evaluated_by', server_src) or \
            re.search(r'payload\[\s*["\']evaluated_by', server_src):
        forge.append("server.py 从请求体读取 evaluated_by")
    report.add("B2-4", "看板写回路径不接受也不传递评估者身份",
               len(forge), 0, not forge, forge)

    # B2-5 两个 wrapper 的子命令集合相同（与回归测试同一套解析规则）。
    bash = _read(os.path.join(ROOT, ".harness", "scripts", "harness"))
    pwsh = _read(os.path.join(ROOT, ".harness", "scripts", "harness.ps1"))
    ignored = {"help", "--help", "-h", "*"}
    bash_cmds = set()
    for line in bash.splitlines():
        hit = re.match(r"^\s{2}([a-z][\w|-]*)\)\s*$", line)
        if hit:
            bash_cmds.update(hit.group(1).split("|"))
    bash_cmds.update(re.findall(r'^if \[ "\$command_name" = "([a-z][\w-]*)" \]',
                                bash, re.M))
    bash_cmds -= ignored
    pwsh_body = pwsh.split("switch ($Command)", 1)
    pwsh_cmds = set(re.findall(r'^\s{4}"([a-z][\w-]*)"\s*\{',
                               pwsh_body[-1], re.M)) - ignored
    report.add("B2-5", "harness 与 harness.ps1 的子命令集合相同",
               "bash %d / ps1 %d" % (len(bash_cmds), len(pwsh_cmds)),
               "相等且非空",
               bool(bash_cmds) and bash_cmds == pwsh_cmds,
               ["只在 bash: %s" % sorted(bash_cmds - pwsh_cmds),
                "只在 ps1: %s" % sorted(pwsh_cmds - bash_cmds)])

    # B3-1 服务端对空 operator 兜底。
    filled = "_fallback_operator" in state_src and \
        re.search(r"if not \(operator or \"\"\)\.strip\(\):", state_src)
    report.add("B3-1", "服务端在 operator 为空时按角色档案兜底",
               bool(filled), True, bool(filled))

    # B3-2 前端日期必须是本地日历日，不能用 toISOString()。
    app = _read(APP_JS)
    tz_problems = []
    # 只看代码，不看注释：文件里有一段专门警告不要用 toISOString 的注释，
    # 按整词搜会被自己的注释绊倒。
    code_only = re.sub(r"//[^\n]*", "", app)
    if re.search(r"\.toISOString\s*\(", code_only):
        tz_problems.append("app.js 仍在调用 toISOString()——那是 UTC 日期，"
                           "UTC+8 晚间会填成昨天")
    if not re.search(r"getFullYear\(\).*getMonth\(\).*getDate\(\)", app, re.S):
        tz_problems.append("app.js 没有用本地日历字段拼日期")
    report.add("B3-2", "预填日期取本地日历日，不用 UTC",
               len(tz_problems), 0, not tz_problems, tz_problems)

    # B3-3 waived 仍要求非空备注；模板只是 placeholder。
    hv_src = _read(os.path.join(ROOT, ".harness", "scripts",
                                "harness_verification.py"))
    note_ok = re.search(r'status == "waived" and not str\(note', hv_src)
    tpl_problems = []
    if not note_ok:
        tpl_problems.append("set_step 不再强制 waived 的豁免说明")
    if re.search(r"\.value\s*=\s*[^;\n]*noteTemplate\(\)", app):
        tpl_problems.append("备注模板被直接填进了输入框的值，而不是 placeholder")
    report.add("B3-3", "waived 仍需理由，备注模板只作为 placeholder",
               len(tpl_problems), 0, not tpl_problems, tpl_problems)

    # B3-4 操作者必须是从档案生成的选择控件，不是纯文本框。
    #
    # 预填只解决「不用打字」；「不用记得有哪些人」要靠选择。档案本来就是为这件
    # 事维护的，界面不把它用起来，那份档案就只是一个没人看的文件。
    picker = []
    if not re.search(r"function operatorPicker\(", app):
        picker.append("没有 operatorPicker()，操作者仍是自由文本框")
    else:
        body = re.search(r"function operatorPicker\(.*?\n\}", app, re.S)
        text = body.group(0) if body else ""
        if 'el("select"' not in text:
            picker.append("operatorPicker 没有生成下拉控件")
        if "operatorOptions()" not in text:
            picker.append("下拉选项不是从角色档案生成的")
    if not re.search(r"function operatorOptions\(.*?STATE\.roles", app, re.S):
        picker.append("operatorOptions 没有读取角色档案")
    # 步骤行必须用它，而不是继续走 textCell。
    row = re.search(r"function renderStepRow\(.*?\n\}", app, re.S)
    if row and "operatorPicker(" not in row.group(0):
        picker.append("renderStepRow 没有使用 operatorPicker")
    report.add("B3-4", "操作者从角色档案下拉选择，不是自由文本框",
               len(picker), 0, not picker, picker)

    # B3-5 角色切换入口存在，且只能切换、不能改档案内容。
    server_get = _read(os.path.join(ROOT, ".harness", "dashboard", "server.py"))
    switch = []
    if "renderRoleSwitch" not in app:
        switch.append("看板没有角色切换控件")
    if not re.search(r'api\("/api/roles",\s*\{\s*action:\s*"use"', app):
        switch.append("切换没有走 /api/roles 的 use 动作")
    if not re.search(r'payload\.get\("action"\)\s*!=\s*"use"', server_get):
        switch.append("服务端没有把 /api/roles 的写入限制为 use")
    report.add("B3-5", "有角色切换入口，且服务端只接受切换动作",
               len(switch), 0, not switch, switch)

    return report


def not_implemented(report, prefix, label):
    """未实现的断言组一律判失败。

    返回「通过」会让这个脚本变成它本来要消灭的那种东西：一个看起来在把关、
    实际上什么都没查的门。红着比假绿好。
    """
    report.add("%s-0" % prefix, "%s尚未实现" % label, "未实现", "已实现", False)


GROUPS = {
    "tokens": check_tokens,
    "layout": check_layout,
    "nav": check_nav,
    "graphs": check_graphs,
    "evidence": check_evidence,
    "roles": check_roles,
}


def main(argv):
    parser = argparse.ArgumentParser(description="看板呈现层契约断言")
    # 可以一次跑多组：change A 的证据是 `tokens nav graphs`，而 `all` 会连
    # change B 尚未实现的两组一起跑（并且如实报红）。
    parser.add_argument("group", nargs="+", choices=sorted(GROUPS) + ["all"])
    parser.add_argument("--json", dest="json_path",
                        help="把完整结果写成证据文件")
    parser.add_argument("--flow", action="store_true",
                        help="graphs：只跑验证流程图断言")
    parser.add_argument("--relations", action="store_true",
                        help="graphs：只跑关系图断言")
    args = parser.parse_args(argv)

    names = []
    for name in args.group:
        if name == "all":
            names.extend(("tokens", "layout", "nav", "graphs", "evidence",
                          "roles"))
        elif name not in names:
            names.append(name)

    reports = []
    for name in names:
        if name == "graphs":
            both = not (args.flow or args.relations)
            reports.append(check_graphs(flow=args.flow or both,
                                        relations=args.relations or both))
        else:
            reports.append(GROUPS[name]())

    failed = print_report(reports)

    if args.json_path:
        payload = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "root": ROOT,
            "group": names,
            "checks": [c for r in reports for c in r.checks],
            "failed": failed,
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)),
                    exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        print("证据已写入 %s" % args.json_path)

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

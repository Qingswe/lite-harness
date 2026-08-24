"""把呈现层契约接进常规测试。

`check-dashboard-contract.py` 是给人和证据用的入口；这里让同一批断言在
`python -m unittest discover` 里也跑一遍，这样样式或导航的回退会在普通测试
里就暴露，而不是等到有人想起来单独跑那个脚本。
"""

import os
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


DASHBOARD_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = DASHBOARD_DIR.parent / "scripts"
CONTRACT = SCRIPTS_DIR / "check-dashboard-contract.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

_spec = importlib.util.spec_from_file_location("dashboard_contract", CONTRACT)
contract = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(contract)


class EvidenceFixture:
    """临时仓库里的证据夹具。

    同时铺出两种布局（平铺 + `<change>/` 子目录）和三种 kind（json/png/log），
    让每条计数断言都有确定的正数输入。证据断言不依赖仓库真实证据：真实证据的
    数量随历史漂移，刚克隆的模板仓库一份也没有，直接跑会出现「0 / 0 合格」
    的空转；仓库真实证据的内容由 `check-dashboard-contract.py` 在回归时
    直接核对。
    """

    def __init__(self):
        import harness_state
        self._old_state_root = harness_state.ROOT
        self._old_contract_root = contract.ROOT
        self._tmp = tempfile.TemporaryDirectory()
        evidence = os.path.join(self._tmp.name, ".harness", "evidence")
        os.makedirs(os.path.join(self._tmp.name, "openspec", "changes"))
        os.makedirs(os.path.join(evidence, "change-2026-08-24"))
        for name in ("flat-a-2026-08-24.json", "flat-b-2026-08-24.png"):
            with open(os.path.join(evidence, name), "wb") as fh:
                fh.write(b"fixture")
        with open(os.path.join(evidence, "change-2026-08-24",
                               "nested-c-2026-08-24.log"), "wb") as fh:
            fh.write(b"fixture")
        harness_state.configure_root(self._tmp.name)
        contract.ROOT = self._tmp.name

    def restore(self):
        import harness_state
        harness_state.configure_root(self._old_state_root)
        contract.ROOT = self._old_contract_root
        self._tmp.cleanup()


class ContractGroupTests(unittest.TestCase):
    def assert_group(self, report):
        failures = [
            "%s %s：实测 %s，期望 %s%s" % (
                check["id"], check["description"], check["actual"],
                check["expected"],
                ("\n    " + "\n    ".join(str(d) for d in check["detail"][:10]))
                if check["detail"] else "")
            for check in report.failed
        ]
        if failures:
            self.fail("\n".join(failures))

    def test_design_tokens(self):
        self.assert_group(contract.check_tokens())

    def test_layout(self):
        self.assert_group(contract.check_layout())

    def test_evidence(self):
        fx = EvidenceFixture()
        try:
            self.assert_group(contract.check_evidence())
        finally:
            fx.restore()

    def test_roles(self):
        self.assert_group(contract.check_roles())

    def test_navigation_tree(self):
        self.assert_group(contract.check_nav())

    def test_verification_flow(self):
        self.assert_group(contract.check_graphs(flow=True, relations=False))


class VerificationFlowTests(unittest.TestCase):
    def test_projection_keeps_the_field_names_the_record_uses(self):
        """投影不能改名又丢字段。

        投影曾把 `pass_when` 改名成 `item` 并且不带 `how`，于是
        `hv.step_summary()` 找不到任何字段，134 个自动步骤在流程图上全部被摘要
        成「该步骤未写明要求」——而记录里写得清清楚楚。
        """
        import harness_state

        state = harness_state.build_state()
        blank = []
        for change in state["changes"]:
            for node in change["verification_flow"]["nodes"]:
                if node["kind"] != "step":
                    continue
                if node["detail"].startswith("（该步骤未写明要求）"):
                    blank.append((change["id"], node["label"]))

        # 少量步骤的记录本身就很薄（迁移占位），图上如实显示是对的；但绝不该
        # 是全部。这里钉一个上限，投影再退化就会撞线。
        total = sum(len(c["steps"]) for c in state["changes"])
        self.assertLess(
            len(blank), max(4, total // 20),
            "太多步骤没有摘要，投影可能又丢字段了：%s" % blank[:8])

    def test_every_step_has_exactly_one_node(self):
        import harness_state

        state = harness_state.build_state()
        for change in state["changes"]:
            flow = change["verification_flow"]
            labels = [n["label"] for n in flow["nodes"] if n["kind"] == "step"]
            self.assertEqual(
                sorted(str(s["id"]) for s in change["steps"]), sorted(labels),
                "%s 的流程图节点与步骤不是一一对应" % change["id"])


class NavigationCoverageTests(unittest.TestCase):
    def test_every_markdown_under_docs_library_is_listed(self):
        """列举本身不能静默丢文件。

        `build_library` 的 quality 分支曾经是非递归的，docs/quality/pitfalls/
        下的三篇文档因此在看板里完全不存在。拿投影去比投影发现不了这种事，
        所以这里直接跟磁盘比。
        """
        import harness_state

        library = harness_state.build_library()
        for key in ("quality", "knowledge", "adr", "architecture"):
            listed = {doc["path"] for doc in library[key]}
            base = Path(harness_state.ROOT) / "docs" / key
            if not base.is_dir():
                continue
            on_disk = {
                str(p.relative_to(harness_state.ROOT)).replace("\\", "/")
                for p in base.rglob("*.md")}
            self.assertEqual(on_disk, listed, "docs/%s 的列举与磁盘不一致" % key)


class ColorHelperTests(unittest.TestCase):
    """颜色工具本身也要有测试。

    上一轮这些断言差点全部空转：间距改写成 var(--s2) 之后，扫 px 字面量得到的
    是「0 条违规 / 共 0 条」——脚本报绿，但它什么都没查。所以工具函数的行为
    要单独钉住。
    """

    def test_chroma_treats_warm_near_white_as_neutral(self):
        # HSL 饱和度会把 #F5F4EE 这种暖白判成高饱和；彩度不会。
        self.assertLess(contract.chroma((0xF5, 0xF4, 0xEE)), 0.05)
        self.assertGreater(contract.chroma((0xE7, 0x9F, 0x83)), 0.3)

    def test_color_mix_is_not_a_literal(self):
        self.assertEqual(
            [], contract.colors_in(
                "color-mix(in srgb, var(--act) 18%, transparent)"))
        self.assertEqual(
            [(79, 140, 255)], contract.colors_in("rgba(79,140,255,.16)"))

    def test_eight_digit_hex_drops_alpha(self):
        self.assertEqual((0x00, 0x00, 0x00), contract.parse_hex("00000099"))

    def test_var_resolution_reaches_the_underlying_pixels(self):
        tokens = {"--s2": "16px", "--gap": "var(--s2)"}
        self.assertEqual("16px", contract.resolve_vars("var(--gap)", tokens))
        self.assertEqual(
            "0 16px", contract.resolve_vars("0 var(--s2)", tokens))

    def test_contrast_ratio_matches_wcag_reference(self):
        # 纯黑对纯白是 21:1，这是 WCAG 的定义上限。
        self.assertAlmostEqual(
            21.0, contract.contrast_ratio((0, 0, 0), (255, 255, 255)), places=2)

    def test_spacing_grid_check_is_not_vacuous(self):
        report = contract.check_tokens()
        grid = next(c for c in report.checks if c["id"] == "A1-4")
        # 「0 / 0 条违规」是通过，但它意味着一条都没查到。
        self.assertNotIn("/ 0", str(grid["actual"]),
                         "8px 栅格断言没有查到任何间距声明")


class LayoutCheckTests(unittest.TestCase):
    """版式断言的「不是空转」保险。

    layout 组里每条计数型断言都可能在被测对象搬家之后悄悄变成零输入——字号断言
    在没有 --fs-* token 时、彩色断言在没有 color: 声明时都会因为没得可查而报绿。
    这几条测试盯的就是那种情况。
    """

    def setUp(self):
        self.checks = {c["id"]: c for c in contract.check_layout().checks}

    def test_font_scale_check_measures_a_real_scale(self):
        scale = self.checks["A5-1b"]
        self.assertNotIn("0 档", str(scale["actual"]),
                         "字号阶梯断言没有找到任何 --fs-* token")

    def test_font_scale_check_covers_every_declaration(self):
        # 「0 条不在阶梯上 / 共 0 档」同样是假绿。
        self.assertNotIn("共 0 档", str(self.checks["A5-1"]["actual"]))

    def test_chromatic_share_check_counts_declarations(self):
        share = self.checks["A5-2c"]
        self.assertNotIn("/ 0 条", str(share["actual"]),
                         "彩色占比断言没有查到任何 color: 声明")

    def test_missing_scale_fails_instead_of_passing(self):
        """把阶梯抽空之后，断言必须报红而不是报「无违规」。"""
        report = contract.Report("layout")
        contract._check_font_scale(report, [], {})
        self.assertTrue(report.failed, "空阶梯下 A5-1/A5-1b 全部报了通过")


class EvidenceCheckTests(unittest.TestCase):
    """证据断言的「不是空转」保险。

    这一组每条都是计数型断言，而计数型断言有两种失效方式：输入被掏空（0 项
    全部合格），或者数的东西与要测的性质无关。下面几条盯的是前者——后者只能
    靠写完先跑一遍、确认它在坏代码上是红的（本轮逐条构造过反例）。

    这些断言跑在 `EvidenceFixture` 临时夹具上：夹具保证计数输入是确定的正数，
    断言与仓库真实证据的数量解耦（真实证据内容由 `check-dashboard-contract.py`
    在回归时直接核对）。
    """

    def setUp(self):
        self._fx = EvidenceFixture()
        self.checks = {c["id"]: c for c in contract.check_evidence().checks}

    def tearDown(self):
        self._fx.restore()

    def test_coverage_check_saw_real_files(self):
        actual = str(self.checks["B1-1"]["actual"])
        self.assertNotIn("磁盘 0", actual, "覆盖断言一个证据文件都没查到")

    def test_classification_check_is_not_vacuous(self):
        # 「0 / 0 项缺分类」是通过，但它意味着一份证据都没查。
        self.assertNotIn("/ 0 项", str(self.checks["B1-2"]["actual"]))

    def test_image_check_saw_real_images(self):
        self.assertNotIn("/ 0 份", str(self.checks["B1-6"]["actual"]),
                         "图片断言没有查到任何图片证据")

    def test_partition_check_saw_real_dimensions(self):
        self.assertNotIn("0 个取值", str(self.checks["B1-4"]["actual"]),
                         "划分断言没有查到任何维度取值")

    def test_empty_repo_fails_instead_of_passing(self):
        """证据目录为空时，覆盖与分类断言必须报红，而不是「0 项全部合格」。"""
        import harness_state
        old = harness_state.ROOT
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, ".harness", "evidence"))
            os.makedirs(os.path.join(tmp, "openspec", "changes"))
            try:
                harness_state.configure_root(tmp)
                old_root, contract.ROOT = contract.ROOT, tmp
                try:
                    report = contract.check_evidence()
                finally:
                    contract.ROOT = old_root
            finally:
                harness_state.configure_root(old)
        failed = {c["id"] for c in report.failed}
        self.assertIn("B1-1", failed, "空证据目录下覆盖断言报了通过")
        self.assertIn("B1-2", failed, "空证据目录下分类断言报了通过")


class RoleCheckTests(unittest.TestCase):
    def setUp(self):
        self.checks = {c["id"]: c for c in contract.check_roles().checks}

    def test_wrapper_parity_check_parsed_real_subcommands(self):
        actual = str(self.checks["B2-5"]["actual"])
        self.assertNotIn("bash 0", actual, "子命令断言没有解析出任何子命令")
        self.assertNotIn("ps1 0", actual, "子命令断言没有解析出任何子命令")

    def test_identity_boundary_check_found_the_function(self):
        detail = " ".join(str(d) for d in self.checks["B2-4"]["detail"])
        self.assertNotIn("找不到 update_verification_step", detail,
                         "身份边界断言没有找到要检查的函数，等于什么都没查")


if __name__ == "__main__":
    unittest.main()
